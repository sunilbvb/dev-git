// API base handling:
// - `file://` pages can't call relative `/api/...`
// - the Control Server runs on 18081 and serves UI assets, but APIs live on 18082
// Use a configurable API origin (persisted) with sensible defaults.
const DEFAULT_API_ORIGIN = 'http://localhost:8086';
const _storedApiOrigin = localStorage.getItem('devgit_api_origin') || '';
const _isFile = (window.location && window.location.protocol === 'file:');
const _isControlServer = (() => {
    try {
        const host = String(window.location.hostname || '');
        const port = String(window.location.port || '');
        return (host === 'localhost' || host === '127.0.0.1' || host === '::1') && port === '18081';
    } catch (_) {
        return false;
    }
})();

// Only honor stored API origin when running from `file://` or the Control Server (18081).
// When running on the dashboard server itself (e.g. http://localhost:8086), use same-origin APIs.
const API_ORIGIN = (_isFile || _isControlServer)
    ? (_storedApiOrigin || DEFAULT_API_ORIGIN)
    : '';

function apiUrl(path) {
    const p = String(path || '');
    if (p.startsWith('http://') || p.startsWith('https://')) return p;
    if (API_ORIGIN) {
        if (p.startsWith('/')) return API_ORIGIN + p;
        return API_ORIGIN + '/' + p;
    }
    return p.startsWith('/') ? p : ('/' + p);
}

function setApiOrigin(origin) {
    const val = String(origin || '').trim();
    if (!val) return;
    localStorage.setItem('devgit_api_origin', val);
}

function getEffectiveApiOrigin() {
    try {
        if (API_ORIGIN) return API_ORIGIN;
        return window.location.origin;
    } catch (_) {
        return API_ORIGIN || DEFAULT_API_ORIGIN;
    }
}

function requestNotificationPermission() {
    if ('Notification' in window) {
        if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }
}

function _looksLikeHtml(text) {
    const t = String(text || '').trim().toLowerCase();
    return t.startsWith('<!doctype') || t.startsWith('<html') || t.includes('<head');
}

function _compareVersions(v1, v2) {
    const p1 = String(v1 || '0').split('.').map(Number);
    const p2 = String(v2 || '0').split('.').map(Number);
    for (let i = 0; i < Math.max(p1.length, p2.length); i++) {
        const n1 = p1[i] || 0;
        const n2 = p2[i] || 0;
        if (n1 !== n2) return n1 - n2;
    }
    return 0;
}

function _copyText(text) {
    return navigator.clipboard.writeText(String(text || ''));
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// Generic async job poller (used by Git/Disk/Translations flows).
// Returns the final job payload when status becomes done/success/error/stopped.
async function pollJob(jobId, opts = {}) {
    const label = String(opts.label || 'Job');
    const intervalMs = Number(opts.intervalMs || 600);
    const timeoutMs = Number(opts.timeoutMs || 10 * 60 * 1000); // 10 min
    const startedAt = Date.now();

    while (true) {
        if ((Date.now() - startedAt) > timeoutMs) {
            throw new Error(`${label} timed out.`);
        }
        const resp = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(String(jobId || ''))}`));
        const data = await resp.json();
        if (!data || !data.success || !data.job) {
            throw new Error((data && (data.error || data.message)) || `${label} failed to read job status`);
        }
        const job = data.job;
        const status = String(job.status || '');
        if (status === 'running' || status === 'stopping') {
            await new Promise(r => setTimeout(r, intervalMs));
            continue;
        }
        // Normalize possible statuses across subsystems.
        if (status === 'success') return { status: 'done', result: job, stdout: job.output || '', stderr: job.error || '' };
        if (status === 'done') return job;
        if (status === 'error') return job;
        if (status === 'stopped') return job;
        // Unknown status: treat as terminal
        return job;
    }
}

async function fetchJsonWithAutoOrigin(path, opts = null) {
    const url = apiUrl(path);
    let res;
    try {
        res = await fetch(url, opts || undefined);
    } catch (err) {
        const defaultUrl = DEFAULT_API_ORIGIN + (String(path || '').startsWith('/') ? String(path) : ('/' + String(path)));
        if (url !== defaultUrl) {
            try {
                res = await fetch(defaultUrl, opts || undefined);
                setApiOrigin(DEFAULT_API_ORIGIN);
            } catch (_) {
                throw err;
            }
        } else {
            throw err;
        }
    }
    const ct = String(res.headers.get('content-type') || '');
    if (ct.includes('application/json')) {
        return await res.json();
    }
    const txt = await res.text();
    // If we got HTML, it usually means we're hitting the wrong server (e.g. control server 18081 or a stale backend).
    // Try the default dashboard API origin once and persist it if it works.
    if (_looksLikeHtml(txt)) {
        try {
            const retryUrl = DEFAULT_API_ORIGIN + (String(path || '').startsWith('/') ? String(path) : ('/' + String(path)));
            const retryRes = await fetch(retryUrl, opts || undefined);
            const retryCt = String(retryRes.headers.get('content-type') || '');
            if (retryCt.includes('application/json')) {
                setApiOrigin(DEFAULT_API_ORIGIN);
                return await retryRes.json();
            }
        } catch (_) {
            // fall through
        }
    }
    throw new Error(`Server returned non-JSON. ${txt ? `(${txt.slice(0, 60)}…)` : ''}`.trim());
}

function formatBytesShort(bytes) {
    const b = Number(bytes || 0);
    if (!Number.isFinite(b) || b <= 0) return '0 B';
    const gb = 1024 * 1024 * 1024;
    const mb = 1024 * 1024;
    if (b >= gb) return `${(b / gb).toFixed(1)} GB`;
    if (b >= mb) return `${(b / mb).toFixed(1)} MB`;
    return `${Math.round(b / 1024)} KB`;
}

function runTerminalSetupJob(command, consoleElId, wrapperId, installBtnOrId, clearBtnId, onComplete = null) {
    const consoleEl = document.getElementById(consoleElId);
    const wrapper = document.getElementById(wrapperId);
    const installBtn = typeof installBtnOrId === 'string' ? document.getElementById(installBtnOrId) : installBtnOrId;
    
    if (!consoleEl) return;
    if (wrapper) wrapper.style.display = 'block';
    
    let originalText = '⚡ Run Install';
    if (installBtn) {
        originalText = installBtn.textContent;
        installBtn.disabled = true;
        installBtn.textContent = '⚡ Running...';
    }
    
    consoleEl.textContent = `> Starting command: ${command}\n`;
    
    fetch(apiUrl('/api/terminal/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: command, shell: 'zsh' })
    })
    .then(r => r.json())
    .then(data => {
        if (!data.success) {
            throw new Error(data.error || "Failed to execute installation command");
        }
        
        const jobId = data.jobId;
        pollSetupJob(jobId, consoleEl, installBtn, originalText, onComplete);
    })
    .catch(err => {
        consoleEl.textContent += `\nError: ${err.message}\n`;
        if (installBtn) {
            installBtn.disabled = false;
            installBtn.textContent = '⚡ Retry Install';
        }
    });
}

function pollSetupJob(jobId, consoleEl, installBtn, originalText, onComplete) {
    fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`))
    .then(r => r.json())
    .then(data => {
        if (!data.success || !data.job) {
            throw new Error(data.error || "Failed to poll job status");
        }
        
        const job = data.job;
        const out = job.output || "";
        const err = job.error || "";
        let combined = out;
        if (err) {
            combined += (combined ? "\n" : "") + err;
        }
        
        consoleEl.textContent = `> ${job.command}\n\n${combined}`;
        consoleEl.scrollTop = consoleEl.scrollHeight;
        
        if (job.status === 'running' || job.status === 'stopping') {
            setTimeout(() => pollSetupJob(jobId, consoleEl, installBtn, originalText, onComplete), 300);
        } else {
            if (installBtn) {
                installBtn.disabled = false;
                if (job.status === 'success') {
                    installBtn.textContent = '⚡ Installed';
                    showToast("Installation completed successfully!", "success");
                } else {
                    installBtn.textContent = originalText;
                    showToast("Installation failed or was stopped.", "error");
                }
            }
            if (onComplete) {
                onComplete(job.status === 'success');
            }
        }
    })
    .catch(err => {
        consoleEl.textContent += `\nPolling error: ${err.message}\n`;
        if (installBtn) {
            installBtn.disabled = false;
            installBtn.textContent = originalText;
        }
    });
}

