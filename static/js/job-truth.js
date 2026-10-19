/*
 * Makes long-running local synthesis observable without changing the worker:
 * a job is only described as producing audio after /chunks returns real files.
 */
(() => {
    const REFRESH_MS = 6000;
    let timer = null;
    let currentJobId = null;
    let latestChunks = [];

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
        }[char]));
    }

    function formatLongDuration(seconds) {
        const value = Number(seconds);
        if (!Number.isFinite(value) || value < 0) return '正在估算';
        if (value < 60) return `约 ${Math.max(1, Math.round(value))} 秒`;
        const minutes = Math.round(value / 60);
        if (minutes < 60) return `约 ${minutes} 分钟`;
        const hours = Math.round(minutes / 60);
        if (hours < 48) return `约 ${hours} 小时`;
        const days = Math.round(hours / 24);
        return `约 ${days} 天`;
    }

    function panel() {
        return document.getElementById('job-truth-panel');
    }

    function activeJob(jobs) {
        return (jobs || []).find((job) => job.status === 'processing' || job.status === 'pausing') || null;
    }

    async function loadChunks(jobId) {
        try {
            const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/chunks`, { cache: 'no-store' });
            const payload = await response.json();
            return payload.success && Array.isArray(payload.chunks) ? payload.chunks : [];
        } catch (_) {
            return [];
        }
    }

    function render(job) {
        const root = panel();
        if (!root) return;
        if (!job) {
            root.hidden = true;
            return;
        }

        root.hidden = false;
        const total = Math.max(0, Number(job.total_chunks) || 0);
        const done = Math.min(Math.max(0, Number(job.processed_chunks) || 0), total || Number.MAX_SAFE_INTEGER);
        const chapterCount = Math.max(0, Number(job.chapter_count) || 0);
        const preview = latestChunks.find((chunk) => chunk && chunk.file_url) || null;
        const isLongBook = total >= 300 || chapterCount >= 20;
        const jobShortId = escapeHtml(String(job.job_id || '').slice(0, 8));
        const audioBlock = preview
            ? `<audio class="job-truth-audio" controls preload="none" src="${escapeHtml(preview.file_url)}"></audio>`
            : '<div class="job-truth-empty-audio">第一个语音片段生成后，会直接在这里出现试听。</div>';
        const longJobNote = isLongBook
            ? '这是整本长篇任务；所有片段完成后，系统还会按章节归档和合并。'
            : '任务完成后会自动归档到音频库。';

        root.innerHTML = `
            <div>
                <div class="job-truth-eyebrow"><i class="job-truth-live-dot" aria-hidden="true"></i>后台正在实际合成语音</div>
                <h3>任务 ${jobShortId} 正在运行</h3>
                <p class="job-truth-copy">已生成 ${done} 段可用语音。页面每 6 秒自动更新；关闭页面不会停止后台制作。</p>
                <div class="job-truth-metrics">
                    <div class="job-truth-metric"><strong>${done.toLocaleString()} / ${total.toLocaleString() || '—'}</strong><span>已完成片段</span></div>
                    <div class="job-truth-metric"><strong>${formatLongDuration(job.eta_seconds)}</strong><span>按当前速度的剩余时间</span></div>
                    <div class="job-truth-metric"><strong>${chapterCount ? chapterCount.toLocaleString() : '单文件'}</strong><span>${chapterCount ? '章节将分别归档' : '输出方式'}</span></div>
                </div>
            </div>
            <div class="job-truth-side">
                <div class="job-truth-audio-label">已生成片段试听</div>
                ${audioBlock}
                <div class="job-truth-actions">
                    <button type="button" class="btn btn-secondary btn-sm" data-job-truth-details="${jobShortId}">查看逐段进度</button>
                </div>
                <div class="job-truth-note">${longJobNote}</div>
            </div>`;

        const detailButton = root.querySelector('[data-job-truth-details]');
        if (detailButton && typeof window.openJobDetailsModal === 'function') {
            detailButton.addEventListener('click', () => window.openJobDetailsModal(job.job_id));
        }
    }

    async function refresh() {
        const root = panel();
        if (!root || document.hidden) return;
        try {
            const response = await fetch('/api/queue', { cache: 'no-store' });
            const payload = await response.json();
            const job = payload.success ? activeJob(payload.jobs) : null;
            if (!job) {
                currentJobId = null;
                latestChunks = [];
                render(null);
                return;
            }
            if (currentJobId !== job.job_id || latestChunks.length !== Number(job.processed_chunks || 0)) {
                currentJobId = job.job_id;
                latestChunks = await loadChunks(job.job_id);
            }
            render(job);
        } catch (_) {
            // The standard queue handles the error state; don't cover it with another warning.
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const queue = document.getElementById('queue-tab');
        const header = queue?.querySelector('.queue-header');
        if (!queue || !header || panel()) return;
        const root = document.createElement('section');
        root.id = 'job-truth-panel';
        root.className = 'job-truth-panel';
        root.hidden = true;
        header.insertAdjacentElement('afterend', root);
        refresh();
        timer = window.setInterval(refresh, REFRESH_MS);
    });

    window.addEventListener('beforeunload', () => {
        if (timer) window.clearInterval(timer);
    });
})();
