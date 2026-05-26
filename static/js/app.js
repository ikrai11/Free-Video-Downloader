// Vault — Frontend Logic

let extractedFormats = [];
let selectedFormatId = null;
let currentTaskId = null;
let eventSource = null;

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// --- Toast ---
function showToast(msg, type) {
  const container = $('#toastContainer');
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

function showError(msg) {
  showToast(msg, 'error');
}
function showSuccess(msg) {
  showToast(msg, 'success');
}

// --- Alerts in card ---
function showCardError(msg) {
  const el = $('#alertError');
  el.textContent = msg;
  el.style.display = 'block';
}
function hideCardError() {
  $('#alertError').style.display = 'none';
}

// --- Format bytes ---
function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '? MB';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
}

function formatDuration(secs) {
  if (!secs || secs <= 0) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// --- Extract ---
async function extractVideo() {
  const url = $('#urlInput').value.trim();
  if (!url) {
    showCardError('请先粘贴视频链接。');
    return;
  }

  hideCardError();
  setExtractLoading(true);

  try {
    const res = await fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!data.success) {
      showCardError(data.error || '视频信息解析失败。');
      return;
    }

    renderResult(data.data);
  } catch (e) {
    showCardError('网络错误，请检查网络连接。');
  } finally {
    setExtractLoading(false);
  }
}

function setExtractLoading(loading) {
  const btn = $('#btnExtract');
  btn.disabled = loading;
  btn.querySelector('.btn__text').style.display = loading ? 'none' : '';
  btn.querySelector('.btn__spinner').style.display = loading ? '' : 'none';
}

// --- Render result ---
function renderResult(data) {
  extractedFormats = data.formats || [];
  selectedFormatId = extractedFormats.length > 0 ? extractedFormats[0].format_id : null;

  if (data.thumbnail) {
    const proxyUrl = '/api/thumbnail?url=' + encodeURIComponent(data.thumbnail);
    const img = $('#thumbImg');
    img.src = proxyUrl;
    img.onerror = function() {
      // If proxy also fails, try direct URL as last resort
      if (this.src !== data.thumbnail) {
        this.src = data.thumbnail;
        this.onerror = function() {
          this.style.display = 'none';
          $('#thumbPlaceholder').style.display = 'flex';
        };
      } else {
        this.style.display = 'none';
        $('#thumbPlaceholder').style.display = 'flex';
      }
    };
    img.onload = function() {
      this.style.display = 'block';
      $('#thumbPlaceholder').style.display = 'none';
    };
    $('#resultThumb').style.display = '';
  } else {
    $('#resultThumb').style.display = 'none';
  }

  $('#resultTitle').textContent = data.title || '无标题';
  $('#metaUploader').textContent = data.uploader || '未知';
  $('#metaDuration').textContent = formatDuration(data.duration);
  $('#metaSource').textContent = data.extractor || '';

  // Render format grid
  const grid = $('#formatGrid');
  grid.innerHTML = '';

  if (extractedFormats.length === 0) {
    grid.innerHTML = '<p style="color:var(--text-muted);font-size:0.88rem;">无可选格式，将使用默认画质。</p>';
  } else {
    extractedFormats.forEach((fmt, idx) => {
      const el = document.createElement('div');
      el.className = 'format-option' + (idx === 0 ? ' format-option--selected' : '');
      el.innerHTML = `
        <span class="format-option__res">${fmt.note || fmt.resolution}</span>
        <span class="format-option__detail">${fmt.ext}${fmt.fps && !fmt.is_audio ? ' · ' + fmt.fps + 'fps' : ''}</span>
        ${fmt.filesize ? `<span class="format-option__size">${formatBytes(fmt.filesize)}</span>` : ''}
      `;
      el.addEventListener('click', () => {
        $$('.format-option').forEach(e => e.classList.remove('format-option--selected'));
        el.classList.add('format-option--selected');
        selectedFormatId = fmt.format_id;
      });
      grid.appendChild(el);
    });
  }

  $('#resultArea').style.display = '';
  $('#progressArea').style.display = 'none';
}

// --- Download ---
function startDownload() {
  const url = $('#urlInput').value.trim();
  if (!url) {
    showError('请先粘贴视频链接。');
    return;
  }
  if (!selectedFormatId && extractedFormats.length > 0) {
    selectedFormatId = extractedFormats[0].format_id;
  }

  hideCardError();
  closeEventSource();

  const btn = $('#btnDownload');
  btn.disabled = true;
  $('#btnDownloadText').textContent = '启动中...';

  fetch('/api/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      format_id: selectedFormatId || 'bestvideo+bestaudio/best',
    }),
  })
    .then(r => r.json())
    .then(data => {
      if (!data.success) {
        showError(data.error || '下载启动失败。');
        resetDownloadBtn();
        return;
      }
      currentTaskId = data.task_id;
      showProgressArea();
      connectProgressStream(currentTaskId);
    })
    .catch(err => {
      showError('网络错误：' + err.message);
      resetDownloadBtn();
    });
}

function resetDownloadBtn() {
  const btn = $('#btnDownload');
  btn.disabled = false;
  $('#btnDownloadText').textContent = '立即下载 — 免费';
}

function showProgressArea() {
  $('#resultArea').style.display = 'none';
  $('#progressArea').style.display = '';
  $('#progressFill').style.width = '0%';
  $('#progressPercent').textContent = '0%';
  $('#statSpeed').textContent = '--';
  $('#statEta').textContent = '--';
  $('#statSize').textContent = '--';
  $('#progressFilename').textContent = '';
}

// --- SSE Progress ---
function connectProgressStream(taskId) {
  eventSource = new EventSource('/api/progress/' + taskId);

  eventSource.addEventListener('progress', (e) => {
    const d = JSON.parse(e.data);
    const pct = parseFloat(d._percent_str || d.percent || 0) || 0;
    $('#progressFill').style.width = pct + '%';
    $('#progressPercent').textContent = pct.toFixed(1) + '%';
    if (d._speed_str) $('#statSpeed').textContent = d._speed_str;
    if (d._eta_str) $('#statEta').textContent = d._eta_str;

    const dl = d.downloaded_bytes || d.total_bytes_estimate;
    const tot = d.total_bytes || d.total_bytes_estimate;
    if (dl && tot) {
      $('#statSize').textContent = formatBytes(dl) + ' / ' + formatBytes(tot);
    } else if (dl) {
      $('#statSize').textContent = formatBytes(dl);
    }
  });

  eventSource.addEventListener('processing', (e) => {
    const d = JSON.parse(e.data);
    $('#progressPercent').textContent = '处理中...';
    $('#statSpeed').textContent = '合并中...';
  });

  eventSource.addEventListener('complete', (e) => {
    const d = JSON.parse(e.data);
    $('#progressFill').style.width = '100%';
    $('#progressPercent').textContent = '完成！';
    $('#statSpeed').textContent = '已完成';
    $('#statEta').textContent = '';
    $('#progressFilename').textContent = d.filename || '';
    eventSource.close();
    eventSource = null;
    resetDownloadBtn();

    showSuccess('下载完成！正在保存文件...');
    if (d.download_url) {
      setTimeout(() => {
        window.location.href = d.download_url;
      }, 500);
    }
  });

  eventSource.addEventListener('error', (e) => {
    let msg = '下载失败。';
    try {
      const d = JSON.parse(e.data);
      msg = d.message || msg;
    } catch (_) {}
    showError(msg);
    closeEventSource();
    resetDownloadBtn();
    $('#progressArea').style.display = 'none';
    $('#resultArea').style.display = '';
  });

  eventSource.onerror = () => {
    if (eventSource && eventSource.readyState === EventSource.CLOSED) {
      // May have closed normally via finished event
      return;
    }
    showError('连接中断，下载可能仍在进行中。');
    closeEventSource();
    resetDownloadBtn();
  };
}

function closeEventSource() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

// --- Keyboard shortcuts ---
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && document.activeElement === $('#urlInput')) {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      if ($('#resultArea').style.display !== 'none') {
        startDownload();
      }
    } else {
      extractVideo();
    }
  }
});

// --- Paste button support: auto-detect Ctrl+V or context menu paste ---
$('#urlInput').addEventListener('paste', () => {
  setTimeout(() => {
    if ($('#urlInput').value.trim()) {
      // Auto-extract on paste — feels magical
      extractVideo();
    }
  }, 100);
});
