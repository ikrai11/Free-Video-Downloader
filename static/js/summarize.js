/**
 * AI Video Summarization — SSE via EventSource
 * Uses standard Server-Sent Events protocol for streaming AI summary.
 * Auto-attaches to the summarize button on DOM ready.
 */
(function () {
  'use strict';

  let summaryEventSource = null;

  // ── Public API ──────────────────────────────────────────────────

  window.summarizeVideo = function () {
    const urlInput = document.querySelector('#urlInput');
    if (!urlInput) return;
    const url = urlInput.value.trim();
    if (!url) {
      window._showToast && window._showToast('请先粘贴视频链接。', 'error');
      return;
    }

    closeSummaryStream();

    const btn = document.querySelector('#btnSummarize');
    const btnText = document.querySelector('#btnSummarizeText');
    const summaryArea = document.querySelector('#summaryArea');
    const summaryContent = document.querySelector('#summaryContent');

    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = '提取字幕中...';
    if (summaryArea) summaryArea.style.display = '';
    if (summaryContent) summaryContent.innerHTML = '<p class="summary-loading">正在提取视频字幕...</p>';

    const encodedUrl = encodeURIComponent(url);
    summaryEventSource = new EventSource('/api/summarize/stream?url=' + encodedUrl);

    let fullText = '';

    summaryEventSource.addEventListener('progress', function (e) {
      const d = JSON.parse(e.data);
      if (summaryContent && d.message) {
        summaryContent.innerHTML = '<p class="summary-loading">' + d.message + '</p>';
      }
    });

    summaryEventSource.addEventListener('chunk', function (e) {
      const d = JSON.parse(e.data);
      if (fullText === '') {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = 'AI 总结';
      }
      fullText += d.text || '';
      if (summaryContent) {
        summaryContent.innerHTML = renderMarkdownSimple(fullText);
        summaryArea.scrollTop = summaryArea.scrollHeight;
      }
    });

    summaryEventSource.addEventListener('complete', function () {
      const label = document.querySelector('.summary-area__label');
      if (label) label.textContent = 'AI 总结完成';
      if (btn) btn.disabled = false;
      if (btnText) btnText.textContent = 'AI 总结';
      closeSummaryStream();
    });

    summaryEventSource.addEventListener('error', function (e) {
      let msg = '总结失败。';
      try {
        const d = JSON.parse(e.data);
        msg = d.message || msg;
      } catch (_) {}
      if (summaryContent) {
        summaryContent.innerHTML = '<p class="summary-error">' + msg + '</p>';
      }
      if (btn) btn.disabled = false;
      if (btnText) btnText.textContent = 'AI 总结';
      closeSummaryStream();
    });

    summaryEventSource.onerror = function () {
      closeSummaryStream();
    };
  };

  function closeSummaryStream() {
    if (summaryEventSource) {
      summaryEventSource.close();
      summaryEventSource = null;
    }
  }

  // ── Simple Markdown → HTML renderer ─────────────────────────────

  function renderMarkdownSimple(text) {
    let html = text
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/^# (.+)$/gm, '<h2>$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
      .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>');

    return '<p>' + html + '</p>';
  }

  // ── Auto-attach to summarize button on DOM ready ────────────────
  function _init() {
    var btn = document.querySelector('#btnSummarize');
    if (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        window.summarizeVideo();
      });
      // Remove inline onclick to avoid double calls with old handler
      btn.removeAttribute('onclick');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();
