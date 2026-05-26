"""AI video summarization: subtitle extraction + DeepSeek API streaming."""
import json
import os
import re
import sys
import tempfile
from openai import OpenAI

_DEEPSEEK_BASE = 'https://api.deepseek.com/v1'
_MAX_SUBTITLE_CHARS = 12000  # ~15K tokens, leaves room for prompt & response


def _load_dotenv():
    """Load key=value pairs from .env file (if exists) into os.environ."""
    paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'),
        '.env',
    ]
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val


_load_dotenv()


def _get_api_key() -> str:
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        raise RuntimeError(
            '请设置 DEEPSEEK_API_KEY 环境变量或在项目根目录创建 .env 文件。\n'
            '获取方式：访问 https://platform.deepseek.com 注册并创建 API Key。\n'
            '配置方法：在项目根目录的 .env 文件中添加 DEEPSEEK_API_KEY=你的key'
        )
    return key


def extract_subtitles(url: str) -> str:
    """Extract subtitle text from a video URL using yt-dlp. Returns plain text."""
    import yt_dlp

    tmpdir = tempfile.mkdtemp(prefix='vault_subs_')
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['zh-Hans', 'zh-CN', 'zh', 'en', 'zh-Hant'],
            'subtitlesformat': 'srt',
            'outtmpl': f'{tmpdir}/%(id)s',
            'socket_timeout': 15,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id', 'unknown')
            title = info.get('title', '')

        # Find the downloaded subtitle file
        sub_text = ''
        for root, _dirs, files in os.walk(tmpdir):
            for fname in sorted(files):
                if fname.endswith(('.srt', '.vtt')):
                    fpath = os.path.join(root, fname)
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    sub_text += _parse_srt(content) + '\n\n'

        if not sub_text:
            raise RuntimeError(
                '该视频没有可用的字幕。\n'
                '目前支持 B站、YouTube 等有自动字幕的平台。'
            )

        # Trim to max chars
        if len(sub_text) > _MAX_SUBTITLE_CHARS:
            sub_text = sub_text[:_MAX_SUBTITLE_CHARS] + '\n...(字幕内容已截断)'

        return sub_text, title
    finally:
        # Clean up temp files
        for root, _dirs, files in os.walk(tmpdir):
            for fname in files:
                try:
                    os.remove(os.path.join(root, fname))
                except OSError:
                    pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def _parse_srt(content: str) -> str:
    """Remove SRT/VTT timestamps and sequence numbers, return plain text."""
    # Remove VTT header
    content = re.sub(r'^WEBVTT.*?\n\n', '', content, flags=re.S)
    # Remove SRT sequence numbers and timestamps
    content = re.sub(r'^\d+\n', '', content, flags=re.M)
    content = re.sub(r'\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}.*\n?', '', content, flags=re.M)
    # Remove VTT timestamps
    content = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*\n?', '', content, flags=re.M)
    # Remove HTML/VTT tags
    content = re.sub(r'<[^>]+>', '', content)
    # Collapse blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


def summarize_stream(subtitle_text: str, title: str, progress_queue):
    """Stream AI summary via DeepSeek API. Pushes events to progress_queue."""
    api_key = _get_api_key()

    progress_queue.put({'status': 'progress', 'message': '正在连接 AI 服务...'})

    client = OpenAI(api_key=api_key, base_url=_DEEPSEEK_BASE)

    prompt = f"""你是一个专业的学习助手。请根据以下视频字幕内容，生成一份结构化的学习笔记。

视频标题：{title}

要求：
1. **视频大纲**：列出视频的主要章节结构（树形列表）
2. **核心知识点**：提炼 3-5 个最重要的知识点，每个知识点用 2-3 句话解释
3. **一句话总结**：用一句话概括整个视频的核心内容

请使用 Markdown 格式输出，语言与字幕语言保持一致。

字幕内容：
{subtitle_text}"""

    progress_queue.put({'status': 'progress', 'message': 'AI 正在生成总结...'})

    try:
        stream = client.chat.completions.create(
            model='deepseek-chat',
            messages=[{'role': 'user', 'content': prompt}],
            stream=True,
            temperature=0.3,
            max_tokens=2000,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                progress_queue.put({
                    'status': 'chunk',
                    'text': delta.content,
                })

        progress_queue.put({'status': 'complete', 'message': '总结完成'})

    except Exception as e:
        msg = str(e)
        if 'API key' in msg.lower() or 'authentication' in msg.lower():
            msg = 'DeepSeek API Key 无效，请检查 DEEPSEEK_API_KEY 环境变量是否正确设置。'
        progress_queue.put({'status': 'error', 'message': msg})
