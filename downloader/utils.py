import os
import re
import time
from urllib.parse import urlparse

BLOCKED_SCHEMES = {'file', 'ftp', 'data', 'javascript', 'vbscript'}
BLOCKED_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'}

_URL_MAX_LEN = 2000
_FILENAME_MAX_LEN = 150


def validate_url(url: str) -> tuple:
    """Return (is_valid, error_message)."""
    if not url or len(url) > _URL_MAX_LEN:
        return False, "URL is empty or too long"

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "Invalid URL format"

    scheme = parsed.scheme.lower()
    if scheme in BLOCKED_SCHEMES:
        return False, f"Unsupported protocol: {parsed.scheme}"
    if scheme not in ('http', 'https'):
        return False, "Only HTTP and HTTPS URLs are supported"

    hostname = (parsed.hostname or '').lower().strip('[]')
    if hostname in BLOCKED_HOSTS:
        return False, "Local addresses are not allowed"

    return True, None


def sanitize_filename(name: str) -> str:
    """Remove path separators and null bytes, limit length."""
    name = name.replace('\x00', '')
    name = name.replace('/', '_').replace('\\', '_')
    name = re.sub(r'[<>:"|?*]', '_', name)
    if len(name) > _FILENAME_MAX_LEN:
        base, ext = os.path.splitext(name)
        name = base[:_FILENAME_MAX_LEN - len(ext)] + ext
    return name.strip()


def cleanup_old_files(directory: str, max_age_seconds: int = 600):
    """Remove files older than max_age_seconds in directory."""
    if not os.path.isdir(directory):
        return
    now = time.time()
    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        try:
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath) > max_age_seconds):
                os.remove(fpath)
        except OSError:
            pass
