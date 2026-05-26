import json
import os
import queue
import threading
import time
import uuid
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, jsonify, Response, send_file, render_template, stream_with_context
from downloader.engine import extract_info, build_format_list, download_video
from downloader.utils import validate_url, sanitize_filename, cleanup_old_files

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

tasks = {}
tasks_lock = threading.Lock()

# Simple rate limiter: {ip: [timestamps]}
rate_map = {}
rate_lock = threading.Lock()
RATE_LIMIT = 10
RATE_WINDOW = 60


def _check_rate(ip: str) -> bool:
    now = time.time()
    with rate_lock:
        times = rate_map.get(ip, [])
        times = [t for t in times if now - t < RATE_WINDOW]
        if len(times) >= RATE_LIMIT:
            rate_map[ip] = times
            return False
        times.append(now)
        rate_map[ip] = times
    return True


def _cleanup_worker():
    while True:
        time.sleep(60)
        now = time.time()
        with tasks_lock:
            expired = []
            for tid, t in tasks.items():
                completed = t.get('completed_at')
                if completed and (now - completed > 600):
                    expired.append(tid)
                    fp = t.get('filepath')
                    if fp and os.path.exists(fp):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
            for tid in expired:
                del tasks[tid]
        cleanup_old_files(DOWNLOAD_DIR, 600)


threading.Thread(target=_cleanup_worker, daemon=True).start()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/extract', methods=['POST'])
def api_extract():
    if not _check_rate(request.remote_addr):
        return jsonify({'success': False, 'error': '请求过于频繁，请稍后再试。'}), 429

    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    ok, err = validate_url(url)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    try:
        info = extract_info(url)
    except Exception as e:
        msg = str(e).split('\n')[0]
        return jsonify({'success': False, 'error': msg or '视频信息解析失败'}), 400

    # Thumbnail: try singular, then plural list, pick highest resolution
    thumbnail_url = info.get('thumbnail', '')
    if not thumbnail_url:
        thumbs = info.get('thumbnails', [])
        if thumbs:
            # Sort by preference/quality — last is usually best
            best = thumbs[-1]
            thumbnail_url = best.get('url', '') if isinstance(best, dict) else str(best)

    if info.get('extractor') == 'douyin':
        formats = info.get('formats', [])
    else:
        formats = build_format_list(info)
    result = {
        'id': info.get('id', ''),
        'title': info.get('title', 'Untitled'),
        'duration': info.get('duration', 0) or 0,
        'thumbnail': thumbnail_url,
        'uploader': info.get('uploader', 'Unknown'),
        'extractor': info.get('extractor', ''),
        'formats': formats,
    }
    return jsonify({'success': True, 'data': result})


@app.route('/api/download', methods=['POST'])
def api_download():
    if not _check_rate(request.remote_addr):
        return jsonify({'success': False, 'error': '请求过于频繁，请稍后再试。'}), 429

    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    format_id = data.get('format_id', 'bestvideo+bestaudio/best')

    ok, err = validate_url(url)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    task_id = uuid.uuid4().hex[:12]
    q = queue.Queue()
    t = {
        'thread': None,
        'progress_queue': q,
        'filepath': None,
        'filename': None,
        'status': 'starting',
        'completed_at': None,
    }

    with tasks_lock:
        tasks[task_id] = t

    def _run():
        download_video(url, format_id, DOWNLOAD_DIR, q)

    thread = threading.Thread(target=_run, daemon=True)
    t['thread'] = thread
    thread.start()

    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': 'started',
    }), 202


@app.route('/api/progress/<task_id>')
def api_progress(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Invalid task'}), 404

    q = task['progress_queue']

    def generate():
        while True:
            try:
                data = q.get(timeout=30)
                status = data.get('status', 'downloading')
                if status == 'downloading':
                    event = 'progress'
                elif status == 'finished':
                    event = 'processing'
                elif status == 'complete':
                    event = 'complete'
                elif status == 'error':
                    event = 'error'
                else:
                    event = status
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

                if status in ('complete', 'error'):
                    with tasks_lock:
                        if status == 'complete':
                            task['status'] = 'completed'
                            task['filepath'] = data.get('filepath')
                            task['filename'] = data.get('filename')
                            task['completed_at'] = time.time()
                            data['download_url'] = f"/api/file/{task_id}/{task['filename']}"
                        else:
                            task['status'] = 'error'
                            task['completed_at'] = time.time()
                    break
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
                with tasks_lock:
                    if task.get('status') in ('completed', 'error'):
                        break

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@app.route('/api/file/<task_id>/<path:filename>')
def api_file(task_id, filename):
    safe_name = sanitize_filename(filename)
    with tasks_lock:
        task = tasks.get(task_id)
    if not task or task.get('status') != 'completed':
        return jsonify({'error': 'File not ready or task not found'}), 404
    if task.get('filename') != safe_name:
        return jsonify({'error': 'Filename mismatch'}), 400

    filepath = task.get('filepath')
    if not filepath or not os.path.isfile(filepath):
        return jsonify({'error': 'File not found'}), 404

    response = send_file(
        filepath,
        as_attachment=True,
        download_name=safe_name,
        mimetype='application/octet-stream',
    )

    @response.call_on_close
    def _cleanup():
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
        with tasks_lock:
            tasks.pop(task_id, None)

    return response


@app.route('/api/thumbnail')
def api_thumbnail():
    """Proxy thumbnail images to avoid browser loading restrictions."""
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': '缺少 url 参数'}), 400

    ok, err = validate_url(url)
    if not ok:
        return jsonify({'error': err}), 400

    import urllib.request
    import ssl
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = resp.read()
            content_type = resp.headers.get('Content-Type', 'image/jpeg')
        return Response(data, mimetype=content_type,
                        headers={'Cache-Control': 'public, max-age=3600'})
    except Exception:
        # Return a 1x1 transparent SVG placeholder on failure
        placeholder = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" '
            b'viewBox="0 0 320 180">'
            b'<rect fill="%231a1a2e" width="320" height="180" rx="8"/>'
            b'<text fill="%23666" font-size="14" font-family="sans-serif" '
            b'text-anchor="middle" x="160" y="96">No Preview</text>'
            b'</svg>'
        )
        return Response(placeholder, mimetype='image/svg+xml')


@app.route('/api/summarize', methods=['POST'])
def api_summarize():
    """Stream AI summary via SSE. Extracts subtitles then calls DeepSeek."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    ok, err = validate_url(url)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    from downloader.summarizer import extract_subtitles, summarize_stream
    import threading
    q = queue.Queue()
    task = {'progress_queue': q, 'status': 'running'}

    def _run():
        try:
            sub_text, title = extract_subtitles(url)
            summarize_stream(sub_text, title, q)
        except Exception as e:
            q.put({'status': 'error', 'message': str(e)})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                data = q.get(timeout=60)
                status = data.get('status', 'progress')
                if status == 'chunk':
                    event = 'chunk'
                elif status == 'complete':
                    event = 'complete'
                elif status == 'error':
                    event = 'error'
                else:
                    event = 'progress'
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                if status in ('complete', 'error'):
                    break
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@app.route('/api/summarize/stream')
def api_summarize_stream():
    """GET SSE stream for AI summary — EventSource-compatible."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': '请提供视频链接参数 ?url=...'}), 400
    ok, err = validate_url(url)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    from downloader.summarizer import extract_subtitles, summarize_stream
    import threading
    q = queue.Queue()

    def _run():
        try:
            sub_text, title = extract_subtitles(url)
            summarize_stream(sub_text, title, q)
        except Exception as e:
            q.put({'status': 'error', 'message': str(e)})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                msg = q.get(timeout=60)
                status = msg.get('status', 'progress')
                if status == 'chunk':
                    event = 'chunk'
                elif status == 'complete':
                    event = 'complete'
                elif status == 'error':
                    event = 'error'
                else:
                    event = 'progress'
                yield f"event: {event}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"

                if status in ('complete', 'error'):
                    break
            except queue.Empty:
                yield "event: heartbeat\ndata: {}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@app.route('/api/health')
def api_health():
    import yt_dlp
    return jsonify({'status': 'ok', 'yt_dlp_version': yt_dlp.version.__version__})


@app.errorhandler(400)
def _bad_request(e):
    return jsonify({'success': False, 'error': '请求参数错误'}), 400


@app.errorhandler(404)
def _not_found(e):
    return jsonify({'success': False, 'error': '页面未找到'}), 404


@app.errorhandler(500)
def _server_error(e):
    return jsonify({'success': False, 'error': '服务器内部错误'}), 500


if __name__ == '__main__':
    print(f"Downloads directory: {DOWNLOAD_DIR}")
    app.run(debug=True, threaded=True, host='localhost', port=5000)
