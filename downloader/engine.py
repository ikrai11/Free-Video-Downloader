import json
import os
import queue
import re
import ssl
import time
import urllib.request
import urllib.parse
import yt_dlp
from yt_dlp.utils import UnsupportedError, DownloadError

_MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
_DOUYIN_HOME = 'https://www.douyin.com/'
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _is_douyin(url: str) -> bool:
    return 'douyin.com' in url


def _resolve_douyin_id(url: str) -> str:
    """Resolve any Douyin URL format to a numeric video ID."""
    # modal_id= query parameter (e.g. /user/self?modal_id=7614000636661794761)
    m = re.search(r'modal_id=(\d+)', url)
    if m:
        return m.group(1)

    # /video/ID format
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)

    # Short link — follow redirect
    if 'v.douyin.com' in url:
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': _MOBILE_UA})
            with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
                final = resp.geturl()
            m = re.search(r'/video/(\d+)', final)
            if m:
                return m.group(1)
            m = re.search(r'/share/video/(\d+)', final)
            if m:
                return m.group(1)
        except Exception:
            pass

    # Try iesdouyin.com share URL
    m = re.search(r'/share/video/(\d+)', url)
    if m:
        return m.group(1)

    return None


def _douyin_fetch_page(url: str) -> str:
    """Fetch Douyin share page HTML."""
    req = urllib.request.Request(url, headers={'User-Agent': _MOBILE_UA})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        raise RuntimeError(f'无法访问抖音页面: {e}')


def _douyin_extract_info(url: str) -> dict:
    """Extract Douyin video info via share-page _ROUTER_DATA JSON."""
    video_id = _resolve_douyin_id(url)
    if not video_id:
        raise RuntimeError('无法从链接中提取视频ID')

    share_url = f'https://www.iesdouyin.com/share/video/{video_id}/'
    html = _douyin_fetch_page(share_url)

    # Parse _ROUTER_DATA JSON from the page
    pattern = re.compile(r'window\._ROUTER_DATA\s*=\s*({.*?})\s*</script>', flags=re.DOTALL)
    m = pattern.search(html)
    if not m:
        raise RuntimeError('无法解析抖音页面数据，页面结构可能已变更')

    router = json.loads(m.group(1))
    loader = router.get('loaderData', {})

    # Find the video item
    item = None
    for key in loader:
        if 'video' in key.lower():
            val = loader[key]
            if isinstance(val, dict):
                item_list = val.get('videoInfoRes', {}).get('item_list', [])
                if item_list:
                    item = item_list[0]
                    break

    if not item:
        raise RuntimeError('未在页面数据中找到视频信息')

    author = item.get('author', {})
    video_data = item.get('video', {})
    play_addr = video_data.get('play_addr', {})
    url_list = play_addr.get('url_list', [])
    download_url = url_list[0].replace('playwm', 'play') if url_list else ''

    cover = video_data.get('cover', {})
    cover_list = cover.get('url_list', [])

    return {
        'id': video_id,
        'title': item.get('desc', '抖音视频'),
        'duration': video_data.get('duration', 0) // 1000,
        'thumbnail': cover_list[0] if cover_list else '',
        'uploader': author.get('nickname', author.get('short_id', '未知')),
        'extractor': 'douyin',
        'formats': [{
            'format_id': 'default',
            'resolution': f"{video_data.get('width', 0)}x{video_data.get('height', 0)}",
            'note': f"{video_data.get('ratio', 'original')}",
            'ext': 'mp4',
            'filesize': None,
            'is_audio': False,
        }] if download_url else [],
        '_douyin_url': download_url,
    }


def _douyin_download(info: dict, output_dir: str, progress_queue: queue.Queue):
    """Download Douyin video directly from the extracted URL."""
    download_url = info.get('_douyin_url', '')
    if not download_url:
        raise RuntimeError('未找到可下载的视频地址')

    safe_title = re.sub(r'[<>:"/\\|?*]', '_', info.get('title', 'douyin'))[:80]
    filename = f'{safe_title} [{info["id"]}].mp4'
    filepath = os.path.join(output_dir, filename)

    req = urllib.request.Request(download_url, headers={
        'User-Agent': _MOBILE_UA,
        'Referer': _DOUYIN_HOME,
    })

    with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
        total = int(resp.headers.get('Content-Length', 0) or 0)
        downloaded = 0
        start_time = time.time()
        with open(filepath, 'wb') as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                elapsed = time.time() - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0
                pct = (downloaded / total * 100) if total > 0 else 0
                progress_queue.put({
                    'status': 'downloading',
                    '_percent_str': f'{pct:.1f}%',
                    '_speed_str': _format_speed(speed),
                    '_eta_str': _format_eta((total - downloaded) / speed) if speed > 0 and total > 0 else '--',
                    'downloaded_bytes': downloaded,
                    'total_bytes': total,
                    'total_bytes_estimate': total,
                })

    progress_queue.put({
        'status': 'complete',
        'filename': os.path.basename(filepath),
        'filepath': filepath,
    })


def _format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1024 * 1024:
        return f'{bytes_per_sec / (1024 * 1024):.1f} MiB/s'
    if bytes_per_sec >= 1024:
        return f'{bytes_per_sec / 1024:.1f} KiB/s'
    return f'{bytes_per_sec:.1f} B/s'


def _format_eta(seconds: float) -> str:
    if seconds >= 3600:
        return f'{int(seconds // 3600)}h{int((seconds % 3600) // 60)}m'
    if seconds >= 60:
        return f'{int(seconds // 60)}m{int(seconds % 60)}s'
    return f'{int(seconds)}s'


# ── Public API (same signatures as before) ─────────────────────────────

def extract_info(url: str) -> dict:
    """Extract video metadata. Routes Douyin to custom parser, others to yt-dlp."""
    if _is_douyin(url):
        return _douyin_extract_info(url)

    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'check_formats': False, 'playlistend': 1, 'noplaylist': True,
        'socket_timeout': 15,
        'http_headers': {'User-Agent': _MOBILE_UA, 'Referer': _DOUYIN_HOME},
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)


def build_format_list(info: dict) -> list:
    """Build a simplified, user-friendly format list from raw info dict."""
    formats = []
    seen = set()

    for f in info.get('formats', []):
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')

        if vcodec == 'none' and acodec != 'none':
            abr = f.get('abr', 0) or 0
            key = f"audio_{abr}"
            if key not in seen and abr > 0:
                seen.add(key)
                fs = f.get('filesize') or f.get('filesize_approx')
                formats.append({
                    'format_id': f['format_id'],
                    'note': f"{abr}kbps audio",
                    'ext': f.get('ext', 'm4a'),
                    'filesize': fs,
                    'resolution': 'audio only',
                    'is_audio': True,
                })

        height = f.get('height')
        if height and height > 0:
            fps = f.get('fps') or 30
            key = f"{height}p_{fps}"
            if key not in seen:
                seen.add(key)
                fs = f.get('filesize') or f.get('filesize_approx')
                formats.append({
                    'format_id': f['format_id'],
                    'resolution': f"{f.get('width', '?')}x{height}",
                    'note': f.get('format_note', f"{height}p"),
                    'ext': f.get('ext', 'mp4'),
                    'filesize': fs,
                    'fps': fps,
                    'vcodec': (f.get('vcodec', '') or 'unknown')[:30],
                    'is_audio': False,
                })

    formats.sort(key=lambda x: (
        x.get('is_audio', False),
        -(int(x.get('resolution', '0').split('x')[-1]) if x.get('resolution', '').split('x')[-1].isdigit() else 0)
    ))
    return formats


def download_video(url: str, format_id: str, output_dir: str, progress_queue: queue.Queue):
    """Download a video. Routes Douyin to custom downloader, others to yt-dlp."""
    if _is_douyin(url):
        info = _douyin_extract_info(url)
        _douyin_download(info, output_dir, progress_queue)
        return

    def hook(d):
        progress_queue.put(d)

    formats_to_try = [format_id]
    if '+' not in format_id and 'best' not in format_id and format_id != 'ba':
        formats_to_try.insert(0, f'{format_id}+bestaudio/best')
    if 'best' not in format_id:
        formats_to_try.append('best')

    last_error = None
    for fmt in formats_to_try:
        try:
            ydl_opts = {
                'quiet': True, 'no_warnings': True, 'format': fmt,
                'outtmpl': f'{output_dir}/%(title).120s [%(id)s].%(ext)s',
                'progress_hooks': [hook], 'merge_output_format': 'mp4',
                'playlistend': 1, 'noplaylist': True,
                'http_headers': {'User-Agent': _MOBILE_UA, 'Referer': _DOUYIN_HOME},
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if not os.path.exists(filepath):
                base = os.path.splitext(filepath)[0]
                for ext in ('.mp4', '.mkv', '.webm', '.m4a', '.mp3'):
                    if os.path.exists(base + ext):
                        filepath = base + ext
                        break
            progress_queue.put({
                'status': 'complete',
                'filename': os.path.basename(filepath),
                'filepath': filepath,
            })
            return
        except Exception as e:
            last_error = e
            continue

    progress_queue.put({'status': 'error', 'message': str(last_error)})
