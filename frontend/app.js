// ==========================================
// Git Operations & AI Commit Panel Logic
// ==========================================

if (typeof window.apiUrl !== 'function') {
    window.apiUrl = function(path) {
        const p = String(path || '');
        if (p.startsWith('http://') || p.startsWith('https://')) return p;
        return p.startsWith('/') ? p : ('/' + p);
    };
}
if (typeof window.escapeHtml !== 'function') {
    window.escapeHtml = function(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };
}

function getEl(id) {
    try {
        return document.getElementById(id) || (window.parent && window.parent.document && window.parent.document.getElementById(id));
    } catch (_) {
        return document.getElementById(id);
    }
}

window.showGitConfirm = (title, message) => {
    return new Promise((resolve) => {
        const modal = document.getElementById('gitConfirmModal');
        const titleEl = document.getElementById('gitConfirmTitle');
        const msgEl = document.getElementById('gitConfirmMessage');
        const okBtn = document.getElementById('gitConfirmOkBtn');
        const cancelBtn = document.getElementById('gitConfirmCancelBtn');
        const closeBtn = document.getElementById('gitConfirmClose');
        
        if (!modal || !titleEl || !msgEl || !okBtn || !cancelBtn) {
            resolve(confirm(message));
            return;
        }
        
        titleEl.textContent = title;
        msgEl.textContent = message;
        
        const cleanup = () => {
            modal.classList.add('hidden');
            okBtn.onclick = null;
            cancelBtn.onclick = null;
            if (closeBtn) closeBtn.onclick = null;
        };
        
        okBtn.onclick = () => {
            cleanup();
            resolve(true);
        };
        
        cancelBtn.onclick = () => {
            cleanup();
            resolve(false);
        };
        
        if (closeBtn) {
            closeBtn.onclick = () => {
                cleanup();
                resolve(false);
            };
        }
        
        modal.classList.remove('hidden');
    });
};

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/** Copy text to the clipboard, falling back to a hidden textarea + execCommand
 *  when the async Clipboard API is unavailable or denied (e.g. insecure context,
 *  missing permission). Returns true on success. */
async function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (_) { /* fall through to legacy fallback */ }
    }
    try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(textarea);
        return ok;
    } catch (_) {
        return false;
    }
}

/** Shorten a long branch/ref path (e.g. "features/my-app/v1.0.4/multi-branch-support-new")
 *  to just its last segment ("…/multi-branch-support-new") for compact card display.
 *  Keeps the shown text a complete word/segment instead of an arbitrary mid-word CSS cut. */
function shortenBranchLabel(branchName) {
    const str = String(branchName || '');
    const parts = str.split('/');
    if (parts.length <= 1) return str;
    return `…/${parts[parts.length - 1]}`;
}

/** Matches a raw `CONFLICT (...): ...` line from git's merge output and pulls out the file path. */
const _GIT_CONFLICT_LINE_RE = /^CONFLICT\s*\([^)]*\):\s*(?:Merge conflict in\s+)?(\S.*)$/i;

/** A line only starts a *new* per-repo block when the text before its first colon looks like an
 *  actual repo/package name (a bare identifier) — not raw git output, which routinely contains a
 *  colon too (e.g. "CONFLICT (content): ...", "error: ..."). Anything that doesn't match is a
 *  continuation of whichever repo block is currently open. */
const _REPO_NAME_RE = /^[A-Za-z0-9_.-]+$/;

/** Render the backend's "<Verb> failed on some repositories:\n<repo>: <msg>\n..." shape as one
 *  card per repo (not one card per line — the previous implementation split the message by '\n' and
 *  colon-sniffed every line independently, which fragmented a single repo's multi-line git output
 *  into a run of bogus "repo" cards like "CONFLICT (CONTENT)"). Each card shows a clean list of
 *  conflicted files up front, with the raw git output available behind a "Show details" toggle. */
function _formatRepoFailureBlocks(message) {
    const lines = message.split('\n');
    const headerText = lines[0];

    const blocks = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        if (!line.trim()) continue;

        const colonIdx = line.indexOf(':');
        const candidate = colonIdx > 0 ? line.slice(0, colonIdx).trim() : '';
        if (candidate && _REPO_NAME_RE.test(candidate)) {
            blocks.push({ repo: candidate, lines: [line.slice(colonIdx + 1).trim()].filter(Boolean) });
        } else if (blocks.length > 0) {
            blocks[blocks.length - 1].lines.push(line.trim());
        }
        // A stray line before any repo has been identified (e.g. a redundant repeat of the
        // summary line itself) is dropped — headerText above already covers it.
    }

    let anyConflicts = false;
    const blocksHtml = blocks.map(b => {
        const rawText = b.lines.join('\n').trim();
        const conflictFiles = b.lines
            .map(l => { const m = l.match(_GIT_CONFLICT_LINE_RE); return m ? m[1].trim() : null; })
            .filter(Boolean);
        if (conflictFiles.length > 0) anyConflicts = true;

        const filesHtml = conflictFiles.length > 0 ? `
            <div style="margin-bottom:10px;">
                <div style="font-size:11px; font-weight:700; color:#fca5a5; text-transform:uppercase; letter-spacing:0.4px; margin-bottom:6px;">Conflicted file${conflictFiles.length === 1 ? '' : 's'} (${conflictFiles.length})</div>
                <ul style="margin:0; padding-left:18px; display:flex; flex-direction:column; gap:4px;">
                    ${conflictFiles.map(f => `<li style="font-family:'JetBrains Mono', monospace; font-size:11.5px; color:#e2e8f0; word-break:break-all;">${escapeHtml(f)}</li>`).join('')}
                </ul>
            </div>
        ` : '';

        // When there's no conflict-file list to lead with, the raw message IS the explanation —
        // surface its first line directly instead of hiding the only useful info behind a click.
        // Once a file list is already shown, the raw lines are redundant technical detail, so they
        // stay tucked away. Either way, anything beyond that first line is available on demand.
        const rawLines = rawText ? rawText.split('\n') : [];
        const leadLine = (conflictFiles.length === 0 && rawLines.length > 0) ? rawLines[0] : '';
        const remainingLines = leadLine ? rawLines.slice(1).join('\n').trim() : rawText;

        const leadLineHtml = leadLine
            ? `<div style="margin-bottom:${remainingLines ? '6px' : '0'};">${escapeHtml(leadLine)}</div>`
            : '';
        const rawDetailsHtml = remainingLines ? `
            <details>
                <summary style="cursor:pointer; font-size:11px; color:#94a3b8; user-select:none;">Show raw git output</summary>
                <div style="margin-top:6px; font-family:'JetBrains Mono', monospace; font-size:11px; white-space:pre-wrap; color:#94a3b8; background:rgba(0,0,0,0.2); border-radius:6px; padding:8px; word-break:break-word;">${escapeHtml(remainingLines)}</div>
            </details>
        ` : '';

        return `
            <div class="ui-card" data-variant="danger" style="margin-bottom: 10px; background: rgba(239, 68, 68, 0.05);">
                <div class="ui-card-header" style="padding: 8px 12px; background: rgba(239, 68, 68, 0.1); border-bottom: 1px solid rgba(239, 68, 68, 0.15);">
                    <span class="ui-card-title" style="color: #ef4444; font-size: 12px;">📂 ${escapeHtml(b.repo)}</span>
                </div>
                <div class="ui-card-body" style="padding: 10px 12px; font-size: 12px; color: #cbd5e1;">
                    ${filesHtml}
                    ${leadLineHtml}
                    ${rawDetailsHtml}
                </div>
            </div>
        `;
    }).join('');

    const nextStepsHtml = anyConflicts ? `
        <div style="margin-bottom:14px; padding:10px 12px; background:rgba(59,130,246,0.08); border-left:3px solid #3b82f6; border-radius:0 6px 6px 0; font-size:12px; color:#cbd5e1; line-height:1.5;">
            💡 Resolve the conflicts in the listed file(s) locally (or use the Conflict Resolution Assistant), then commit and push before retrying.
        </div>
    ` : '';

    return `
        <div style="font-weight: 600; font-size: 13.5px; color: #f8fafc; margin-bottom: 12px;">${escapeHtml(headerText)}</div>
        ${nextStepsHtml}
        <div style="display: flex; flex-direction: column; gap: 4px;">
            ${blocksHtml || `<div style="color:#94a3b8; font-size:12px; white-space:pre-wrap;">${escapeHtml(message)}</div>`}
        </div>
    `;
}

function formatAlertMessage(message) {
    if (!message) return '';

    // The backend reports multi-repo failures (pull/push/fetch/checkout/rename/merge) as
    // "<Verb> failed on some repositories:\n<repo>: <msg>\n...". Detect that shape generically
    // rather than hardcoding every verb.
    if (/failed on some repos(?:itories)?:/i.test(message)) {
        return _formatRepoFailureBlocks(message);
    }

    // Normal text message
    return `<div style="white-space: pre-wrap; line-height: 1.6; font-size: 13px;">${escapeHtml(message)}</div>`;
}

window.showGitAlert = (title, message) => {
    return new Promise((resolve) => {
        const modal = document.getElementById('gitAlertModal');
        const titleEl = document.getElementById('gitAlertTitle');
        const msgEl = document.getElementById('gitAlertMessage');
        const okBtn = document.getElementById('gitAlertOkBtn');
        const closeBtn = document.getElementById('gitAlertClose');
        
        if (!modal || !titleEl || !msgEl || !okBtn) {
            nativeAlert(message);
            resolve();
            return;
        }
        
        titleEl.textContent = title;
        msgEl.innerHTML = formatAlertMessage(message);
        
        const cleanup = () => {
            modal.classList.add('hidden');
            okBtn.onclick = null;
            if (closeBtn) closeBtn.onclick = null;
        };
        
        okBtn.onclick = () => {
            cleanup();
            resolve();
        };
        
        if (closeBtn) {
            closeBtn.onclick = () => {
                cleanup();
                resolve();
            };
        }
        
        modal.classList.remove('hidden');
    });
};

const nativeAlert = window.alert;
window.alert = (message) => {
    window.showGitAlert("⚠️ Dashboard Alert", message);
};

let _gitFetchJobId = null;
let _gitFetchScope = 'all';
let _gitFetchRepoPath = '';
const _gitFetchRepoLocks = new Map();
const _gitBranchChoices = new Map(); // repoPath -> branchName
const _gitBranchStatusCache = new Map(); // repoPath -> branches payload (includes branchStatuses)
window._gitBranchStatusCache = _gitBranchStatusCache;
const _gitConflictRepos = new Map(); // repoPath -> error message
const _gitFavorites = new Set(JSON.parse(localStorage.getItem('devgit_favorites_v1') || '[]'));
const _gitOpHistory = JSON.parse(localStorage.getItem('devgit_op_history_v1') || '{}');
const _gitFilters = { dirty: false, behind: false, ahead: false, conflict: false };
const _gitProtectedBranches = ['main', 'master', 'production', 'release'];
const _gitLastStatusByRepo = new Map();
let _appsConfigCache = [];
let _gitLastModalText = '';
function _applyGitDeltaAnimation(repoPath, prevAhead, prevBehind, nextAhead, nextBehind) {
    const pathEnc = encodeURIComponent(String(repoPath || ''));
    const card = document.querySelector(`.git-repo[data-repo-path-enc="${pathEnc}"]`);
    if (!card) return;
    if (prevAhead !== nextAhead || prevBehind !== nextBehind) {
        card.classList.add('pulse');
        setTimeout(() => card.classList.remove('pulse'), 1200);
    }
}
function showGitInfoModal(title, body) {
    const modal = document.getElementById('gitInfoModal');
    const ttl = document.getElementById('gitInfoModalTitle');
    const pre = document.getElementById('gitInfoModalBody');
    if (!modal || !ttl || !pre) return;
    ttl.textContent = String(title || 'Git Info');
    pre.textContent = String(body || '');
    _gitLastModalText = String(body || '');
    modal.classList.remove('hidden');
}
function hideGitInfoModal() {
    const modal = document.getElementById('gitInfoModal');
    if (!modal) return;
    modal.classList.add('hidden');
}
function _saveGitState() {
    try { localStorage.setItem('devgit_favorites_v1', JSON.stringify(Array.from(_gitFavorites))); } catch (_) {}
    try { localStorage.setItem('devgit_op_history_v1', JSON.stringify(_gitOpHistory)); } catch (_) {}
}
function _pushGitHistory(repoPath, action, ok, durationMs) {
    const key = String(repoPath || '');
    const arr = Array.isArray(_gitOpHistory[key]) ? _gitOpHistory[key] : [];
    arr.unshift({ action, ok: !!ok, durationMs: Number(durationMs || 0), at: Date.now() });
    _gitOpHistory[key] = arr.slice(0, 5);
    _saveGitState();
}
let _gitLastRenderedRepos = [];
let _gitBranchPrefetchRunning = false;


// --- AI Commit state (persisted) ---
const AI_COMMIT_CACHE_KEY = 'devgit_ai_commit_cache_v1';
function _loadAiCommitCache() {
    try {
        const raw = localStorage.getItem(AI_COMMIT_CACHE_KEY);
        const obj = raw ? JSON.parse(raw) : {};
        return (obj && typeof obj === 'object') ? obj : {};
    } catch (_) {
        return {};
    }
}
function _saveAiCommitCache(cache) {
    try {
        localStorage.setItem(AI_COMMIT_CACHE_KEY, JSON.stringify(cache || {}));
    } catch (_) {}
}
function _aiKey(repoPath, branch) {
    return `${String(repoPath || '')}::${String(branch || '')}`;
}
function _getAiState(repoPath, branch) {
    const cache = _loadAiCommitCache();
    return cache[_aiKey(repoPath, branch)] || null;
}
function _setAiState(repoPath, branch, state) {
    const cache = _loadAiCommitCache();
    cache[_aiKey(repoPath, branch)] = { ...(state || {}), updatedAt: Date.now() };
    _saveAiCommitCache(cache);
}
function _clearAiState(repoPath, branch) {
    const cache = _loadAiCommitCache();
    delete cache[_aiKey(repoPath, branch)];
    _saveAiCommitCache(cache);
}



/** Render shimmer skeleton cards while loading repos */
function renderGitShimmers() {
    const listApps = document.getElementById('gitRepoListApps');
    const listPackages = document.getElementById('gitRepoListPackages');

    const makeShimmerCard = () => `
        <div class="compact-app-card">
            <span class="ui-skeleton" style="width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0;"></span>
            <div style="min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 6px;">
                <span class="ui-skeleton ui-skeleton-line" style="width: 60%; height: 12px; margin: 0;"></span>
                <span class="ui-skeleton ui-skeleton-line" style="width: 40%; height: 10px; margin: 0;"></span>
            </div>
            <span class="ui-skeleton" style="width: 45px; height: 16px; border-radius: 10px; flex-shrink: 0;"></span>
        </div>
    `;

    const appShimmers = Array(4).fill(0).map(makeShimmerCard).join('');
    const packageShimmers = Array(6).fill(0).map(makeShimmerCard).join('');

    if (listApps) listApps.innerHTML = appShimmers;
    if (listPackages) listPackages.innerHTML = packageShimmers;
}

window.renderGitShimmers = renderGitShimmers;

function renderGitRepos(repos) {
    const listFav = document.getElementById('gitRepoListFavorites');
    const listApps = document.getElementById('gitRepoListApps');
    const listPackages = document.getElementById('gitRepoListPackages');
    if (!listApps || !listPackages) return;

    // Populate Git Terminal repository select dropdown
    const termSelect = document.getElementById('gitTerminalRepoSelect');
    if (termSelect && Array.isArray(repos)) {
        const prevVal = termSelect.value;
        termSelect.innerHTML = '<option value="">-- Select Repo --</option>';
        repos.forEach((repo) => {
            if (repo && repo.path && repo.name) {
                const opt = document.createElement('option');
                opt.value = repo.path;
                opt.textContent = repo.name;
                termSelect.appendChild(opt);
            }
        });
        if (prevVal && repos.some(r => r.path === prevVal)) {
            termSelect.value = prevVal;
        } else if (repos.length > 0 && !termSelect.value) {
            const workspaceRepo = repos.find(r => r.name.toLowerCase() === 'workspace' || r.name.toLowerCase() === 'root');
            if (workspaceRepo) {
                termSelect.value = workspaceRepo.path;
            } else if (repos[0]) {
                termSelect.value = repos[0].path;
            }
        }
        if (typeof updateTerminalPrompt === 'function') {
            updateTerminalPrompt();
        }
    }

    // Populate Git Stash repository select dropdown
    const stashSelect = document.getElementById('gitStashRepoSelect');
    if (stashSelect && Array.isArray(repos)) {
        const prevVal = stashSelect.value;
        stashSelect.innerHTML = '<option value="">-- Select Repo --</option>';
        repos.forEach((repo) => {
            if (repo && repo.path && repo.name) {
                const opt = document.createElement('option');
                opt.value = repo.path;
                opt.textContent = repo.name;
                stashSelect.appendChild(opt);
            }
        });
        if (prevVal && repos.some(r => r.path === prevVal)) {
            stashSelect.value = prevVal;
        } else if (repos.length > 0 && !stashSelect.value) {
            const workspaceRepo = repos.find(r => r.name.toLowerCase() === 'workspace' || r.name.toLowerCase() === 'root');
            if (workspaceRepo) {
                stashSelect.value = workspaceRepo.path;
            } else if (repos[0]) {
                stashSelect.value = repos[0].path;
            }
        }
        // Asynchronously load stashes for selected repo on init/reload
        if (stashSelect.value) {
            setTimeout(() => { loadGitStashes(stashSelect.value); }, 100);
        }
    }

    if (!Array.isArray(repos) || repos.length === 0) {
        if (listApps) {
            listApps.innerHTML = `
                <div class="ui-card" data-variant="flat" style="grid-column: 1 / -1; padding: 24px; text-align: center; border-color: #1e293b; background: rgba(15, 23, 42, 0.4);">
                    <div style="font-size: 24px; margin-bottom: 8px;">📂</div>
                    <div style="font-size: 14px; font-weight: 600; color: #cbd5e1;">No Repositories Detected</div>
                    <div style="font-size: 12px; color: #64748b; margin-top: 4px;">Click "Refresh Repositories" above to scan the workspace.</div>
                </div>
            `;
        }
        if (listPackages) listPackages.innerHTML = '';
        return;
    }

    const mkRow = (r) => {
        try {
            const prev = _gitLastStatusByRepo.get(String(r.path || '')) || {};
            const name = escapeHtml(r.name || '');
            const branchName = String(r.branch || '');
            const rawPath = String(r.path || '');
            const pathEnc = encodeURIComponent(rawPath);
            const behind = Number(r.behind || 0);
            const ahead = Number(r.ahead || 0);
            _applyGitDeltaAnimation(rawPath, Number(prev.ahead || 0), Number(prev.behind || 0), ahead, behind);
            _gitLastStatusByRepo.set(rawPath, { ahead, behind });
            const dirty = !!r.dirty;

            // Status badge label (only for actionable states)
            let statusBadge = '';
            if (_gitConflictRepos.has(rawPath)) {
                statusBadge = `<span class="ui-badge" data-variant="danger">conflict</span>`;
            } else if (dirty) {
                const n = (r.dirtyFiles || []).length;
                statusBadge = `<span class="ui-badge" data-variant="warning">${n} change${n !== 1 ? 's' : ''}</span>`;
            } else if (behind > 0 && ahead > 0) {
                statusBadge = `<span class="ui-badge" data-variant="warning">↑${ahead} ↓${behind}</span>`;
            } else if (behind > 0) {
                statusBadge = `<span class="ui-badge" data-variant="primary">↓${behind} behind</span>`;
            } else if (ahead > 0) {
                statusBadge = `<span class="ui-badge" data-variant="success">↑${ahead} ahead</span>`;
            }

            // Branch count from cache, fallback to placeholder
            const repoBranchPayload = _gitBranchStatusCache.get(rawPath);
            const branchCount = repoBranchPayload
                ? ((repoBranchPayload.branches || []).length)
                : (r.branchCount || '—');
            const branchCountLabel = branchCount === '—' ? '— branches' : `${branchCount} branch${branchCount === 1 ? '' : 'es'}`;

            // Identify if it's an app and load its icon
            const appName = rawPath.split('/').pop().toLowerCase();
            let lucideIcon = 'folder';
            let headerIcon = '';
            const isPackage = rawPath.includes('/packages/');

            if (!isPackage) {
                const configItem = Array.isArray(_appsConfigCache)
                    ? _appsConfigCache.find(a => a && a.id && String(a.id).toLowerCase() === appName)
                    : null;
                if (configItem && configItem.customIconUrl) {
                    let iconUrl = configItem.customIconUrl;
                    if (iconUrl.startsWith('http') || iconUrl.startsWith('/')) {
                        iconUrl = apiUrl('/api/app-icon?url=' + encodeURIComponent(iconUrl));
                    } else if (!isPackage && !iconUrl.startsWith('/api/')) {
                        iconUrl = `/workspace_assets/${iconUrl}`;
                    }
                    headerIcon = `<img src="${iconUrl}" style="width: 18px; height: 18px; border-radius: 4px; object-fit: contain;" />`;
                } else {
                    lucideIcon = 'package';
                    headerIcon = `<i data-lucide="${lucideIcon}" style="width: 18px; height: 18px; color: #3b82f6; display: inline-flex; align-items: center; justify-content: center;"></i>`;
                }
            } else {
                headerIcon = `<i data-lucide="package" style="width: 18px; height: 18px; color: #64748b; display: inline-flex; align-items: center; justify-content: center;"></i>`;
            }

            return `
                <div class="compact-app-card git-repo" data-repo-path-enc="${pathEnc}" onclick="openRepoDetailScreen('${rawPath.replace(/'/g, "\\'")}')" style="--app-color: #3b82f6;">
                    <div class="compact-app-card-icon">${headerIcon || '<i data-lucide="box"></i>'}</div>
                    <div style="min-width: 0; flex: 1;">
                        <h3 title="${escapeHtml(name)}">${escapeHtml(name)}</h3>
                        <div class="compact-app-meta" title="${escapeHtml(branchName)}"><span class="compact-app-meta-icon">⌥</span><span class="compact-app-meta-text">${escapeHtml(shortenBranchLabel(branchName))}</span></div>
                    </div>
                    ${statusBadge || '<span class="ui-badge" data-variant="neutral">stable</span>'}
                </div>
            `;
        } catch (err) {
            console.error("Error building row for repo:", r, err);
            return '';
        }
    };

    const apps = [];
    const packages = [];
    const others = [];
    const favs = [];

    for (const r of repos) {
        const b = Number(r.behind || 0), a = Number(r.ahead || 0), d = !!r.dirty, c = _gitConflictRepos.has(String(r.path || ''));
        if ((_gitFilters.dirty && !d) || (_gitFilters.behind && !(b > 0)) || (_gitFilters.ahead && !(a > 0)) || (_gitFilters.conflict && !c)) continue;
        const p = String(r.path || '');
        if (_gitFavorites.has(p)) favs.push(r);
        if (p.includes('/apps/')) apps.push(r);
        else if (p.includes('/packages/')) packages.push(r);
        else others.push(r);
    }

    const favHtml = favs.map(mkRow).join('') || '<div style="color:#aaa;">No favorites yet.</div>';
    const appsHtml = apps.map(mkRow).join('') || '<div style="color:#aaa;">No app repos found.</div>';
    const packagesHtml = packages.map(mkRow).join('') || '<div style="color:#aaa;">No package repos found.</div>';
    const othersHtml = others.length ? others.map(mkRow).join('') : '';

    if (listFav) listFav.innerHTML = favHtml;
    listApps.innerHTML = appsHtml;
    listPackages.innerHTML = packagesHtml + othersHtml;
    _gitLastRenderedRepos = Array.isArray(repos) ? repos : [];
    
    if (window.lucide) {
        window.lucide.createIcons();
    }
}


function setGitStatus(text, kind = null) {
    const el = document.getElementById('gitStatus');
    if (!el) return;
    el.textContent = text;
    el.style.color = kind === 'error' ? '#ff8a8a' : kind === 'success' ? '#8fe0a1' : '#aaa';
}

// ─────────────────────────────────────────────────────────────────────────────
// SCREEN 2: Repository Branch Detail View
// ─────────────────────────────────────────────────────────────────────────────

let _gs2ActiveRepoPath = '';
let _gs2AllBranches = [];
let _gs2ActiveGroupKey = 'all';

/** Navigate from Screen 1 card click → Screen 2 detail view */
window.openRepoDetailScreen = async function openRepoDetailScreen(rawPath, silent = false) {
    _gs2ActiveRepoPath = rawPath;
    _gs2ActiveGroupKey = 'all';

    // Automatically select/sync the repository path with the Gitflow module
    if (typeof window.selectGitflowRepo === 'function') {
        window.selectGitflowRepo(rawPath);
    }

    const screen1 = document.getElementById('gitScreen1');
    const screen2 = document.getElementById('gitScreen2');
    const spinner  = document.getElementById('gs2Spinner');
    const body     = document.getElementById('gs2Body');
    const nameEl   = document.getElementById('gs2RepoName');
    const branchEl = document.getElementById('gs2ActiveBranch');
    const badgeEl  = document.getElementById('gs2StatusBadge');
    const countEl  = document.getElementById('gs2BranchCount');

    if (!screen1 || !screen2 || !body) return;

    try {
        // Look up repo meta from last rendered data
        const repo = (_gitLastRenderedRepos || []).find(r => String(r.path || '') === rawPath) || {};
        const repoName = repo.name || rawPath.split('/').pop() || rawPath;

        // Show Screen 2
        screen1.classList.add('hidden');
        screen2.classList.remove('hidden');
        if (nameEl) nameEl.textContent = repoName;

        if (!silent) {
            if (branchEl) {
                branchEl.textContent = '';
                branchEl.classList.add('hidden');
            }
            if (badgeEl) {
                badgeEl.textContent = 'Loading…';
                badgeEl.className = 'gs2-status-badge';
            }
            if (countEl) countEl.textContent = '';
            body.innerHTML = '';

            // Show spinner
            if (spinner) {
                spinner.style.display = 'flex';
                body.appendChild(spinner);
            }
        }

        // Lazy-fetch branch data (use cache if available)
        let data = _gitBranchStatusCache.get(rawPath);
        let triggerFullFetch = false;

        if (!data) {
            // First, fetch branches quickly without ahead/behind calculations to render Screen 2 instantly
            try {
                data = await loadRepoBranches(rawPath, true);
                _gitBranchStatusCache.set(rawPath, data);
                triggerFullFetch = true;
            } catch (err) {
                if (!silent) {
                    if (spinner) spinner.style.display = 'none';
                    body.innerHTML = `<div class="ui-card" data-variant="flat" style="padding: 24px; text-align: center; border-color: #ef4444; background: rgba(239, 68, 68, 0.05);">
                        <div style="font-size: 14px; font-weight: 700; color: #ef4444;">⚠️ Failed to load branches</div>
                        <div style="font-size: 12px; color: #cbd5e1; margin-top: 6px;">${escapeHtml(String(err.message || err))}</div>
                    </div>`;
                }
                if (branchEl) {
                    branchEl.classList.add('hidden');
                }
                _gs2SetStatus(repo, []);
                return;
            }
        } else if (data.quick) {
            triggerFullFetch = true;
        }

    if (!silent && spinner) spinner.style.display = 'none';

    // Helper to render branch details
    const renderData = (payload) => {
        if (branchEl && payload.head) {
            branchEl.textContent = payload.head;
            branchEl.classList.remove('hidden');
        } else if (branchEl) {
            branchEl.classList.add('hidden');
        }

        const branchStatuses = Array.isArray(payload.branchStatuses) ? payload.branchStatuses : [];
        branchStatuses.sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0));
        _gs2AllBranches = branchStatuses;

        _gs2SetStatus(repo, branchStatuses);
        countEl.textContent = `${branchStatuses.length} branch${branchStatuses.length !== 1 ? 'es' : ''}`;

        // Clear search if not silent
        if (!silent) {
            const searchEl = document.getElementById('gs2SearchInput');
            const clearBtn = document.getElementById('gs2SearchClear');
            if (searchEl) searchEl.value = '';
            if (clearBtn) clearBtn.classList.add('hidden');
        }

        _gs2RenderBody(rawPath, branchStatuses, payload.head || '');
    };

    // Initial render (instant)
    renderData(data);

    // Asynchronously fetch full commit statuses in the background if we loaded quick data
    if (triggerFullFetch) {
        loadRepoBranches(rawPath, false)
            .then(fullData => {
                // Verify we are still viewing the same repository details screen
                if (_gs2ActiveRepoPath === rawPath) {
                    _gitBranchStatusCache.set(rawPath, fullData);
                    renderData(fullData);
                }
            })
            .catch(err => {
                console.warn("Background branch sync failed:", err);
            });
    }
    } catch (err) {
        console.error("Error opening repo detail screen:", err);
        if (screen1 && screen2) {
            screen1.classList.remove('hidden');
            screen2.classList.add('hidden');
        }
        setGitStatus(`Failed to open branch details for ${rawPath}: ${err.message}`, 'error');
    }
}

/** Update the status badge in Screen 2 top bar */
function _gs2SetStatus(repo, branches) {
    const badgeEl = document.getElementById('gs2StatusBadge');
    if (!badgeEl) return;
    const hasPending = branches.some(b => (Number(b.ahead) > 0 || Number(b.behind) > 0));
    const isConflict = _gitConflictRepos.has(_gs2ActiveRepoPath);
    if (isConflict) {
        badgeEl.textContent = 'Conflict';
        badgeEl.className = 'ui-badge';
        badgeEl.setAttribute('data-variant', 'danger');
    } else if (hasPending) {
        badgeEl.textContent = 'Pending Changes';
        badgeEl.className = 'ui-badge';
        badgeEl.setAttribute('data-variant', 'warning');
    } else {
        badgeEl.textContent = 'Up-to-Date';
        badgeEl.className = 'ui-badge';
        badgeEl.setAttribute('data-variant', 'success');
    }
}

/** Render Screen 2 body: Pending Actions + a tab bar of Categorized Branch groups */
function _gs2RenderBody(rawPath, branches, head) {
    const body = document.getElementById('gs2Body');
    if (!body) return;

    const pending = branches.filter(b => Number(b.ahead || 0) > 0 || Number(b.behind || 0) > 0);
    const pendingHtml = _gs2BuildPendingSection(rawPath, pending, head);

    const groups = _gs2GroupBranches(branches);

    // The previously-selected tab may not exist anymore (e.g. a search narrowed the
    // groups, or the last branch in that category was deleted) — fall back to "All".
    const validKeys = new Set(groups.map(g => g.colorKey));
    if (_gs2ActiveGroupKey !== 'all' && !validKeys.has(_gs2ActiveGroupKey)) {
        _gs2ActiveGroupKey = 'all';
    }

    const tabBarHtml = groups.length > 0 ? _gs2BuildTabBar(groups, _gs2ActiveGroupKey) : '';
    const visibleGroups = _gs2ActiveGroupKey === 'all' ? groups : groups.filter(g => g.colorKey === _gs2ActiveGroupKey);

    let groupsHtml;
    if (groups.length === 0) {
        groupsHtml = `<div style="text-align:center; color:#94a3b8; padding:40px; font-size:13px;">No branches match your search.</div>`;
    } else if (visibleGroups.length === 0) {
        groupsHtml = `<div style="text-align:center; color:#94a3b8; padding:40px; font-size:13px;">No branches match your search in this category. Try the "All" tab.</div>`;
    } else {
        groupsHtml = _gs2BuildGroupSections(rawPath, visibleGroups, head);
    }

    body.innerHTML = pendingHtml + tabBarHtml + groupsHtml;
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

/** Build the category tab bar (All + one tab per dynamically-discovered branch prefix group) */
function _gs2BuildTabBar(groups, activeKey) {
    const totalCount = groups.reduce((sum, g) => sum + g.branches.length, 0);
    const tabs = [{ key: 'all', label: 'All', count: totalCount }].concat(
        groups.map(g => ({ key: g.colorKey, label: g.label, count: g.branches.length }))
    );

    const itemsHtml = tabs.map(t => {
        const isActive = t.key === activeKey;
        const safeKey = escapeHtml(t.key).replace(/'/g, "\\'");
        // On the active (solid-fill) segment, a default translucent-indigo badge would blend
        // into the indigo background, so it gets a light overlay chip instead for contrast.
        const badgeStyle = isActive
            ? 'font-size:10px; padding:1px 6px; background:rgba(255,255,255,0.22); color:#fff; border-color:rgba(255,255,255,0.35);'
            : 'font-size:10px; padding:1px 6px;';
        return `
            <button type="button" class="ui-segmented-item${isActive ? ' ui-active' : ''}" data-group-key="${escapeHtml(t.key)}" aria-pressed="${isActive}" onclick="_gs2SelectGroupTab('${safeKey}')" style="flex: 0 0 auto;">
                ${escapeHtml(t.label)}
                <span class="ui-badge" data-variant="neutral" style="${badgeStyle}">${t.count}</span>
            </button>
        `;
    }).join('');

    return `
        <div style="overflow-x:auto; margin-bottom:16px;">
            <div class="ui-segmented" data-width="auto" role="tablist" aria-label="Branch categories" style="width:max-content;">
                ${itemsHtml}
            </div>
        </div>
    `;
}

/** Switch the active branch-category tab, preserving whatever search query is active */
function _gs2SelectGroupTab(key) {
    _gs2ActiveGroupKey = key;
    const searchEl = document.getElementById('gs2SearchInput');
    _gs2FilterBranches(searchEl ? searchEl.value : '');
}

/** Build the "Pending Actions" section at top of Screen 2 */
function _gs2BuildPendingSection(rawPath, pending, head) {
    if (pending.length === 0) return '';

    const cards = pending.map(b => {
        const name = escapeHtml(b.name || '');
        const behind = Number(b.behind || 0);
        const ahead  = Number(b.ahead  || 0);
        const isHead = b.name === head;
        const escapedName = (b.name || '').replace(/'/g, "\\'");
        const escapedPath = rawPath.replace(/'/g, "\\'");
        let statusLine = '';
        if (behind > 0 && ahead > 0) statusLine = `<span class="ui-badge" data-variant="warning">↑${ahead} ↓${behind}</span>`;
        else if (behind > 0) statusLine = `<span class="ui-badge" data-variant="primary">↓${behind} behind</span>`;
        else if (ahead > 0) statusLine = `<span class="ui-badge" data-variant="success">↑${ahead} ahead</span>`;

        return `
            <div class="ui-card" data-variant="interactive" data-branch-name="${name.toLowerCase()}" style="min-height: 120px; display: flex; flex-direction: column; justify-content: space-between; ${isHead ? 'border-color: #3b82f6; background: rgba(59, 130, 246, 0.1); box-shadow: 0 0 0 1px #3b82f6;' : ''}">
                <div class="ui-card-header" style="padding: 10px 14px; background: transparent; border-bottom: none; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
                        <div class="compact-app-card-icon" style="--app-color: ${isHead ? '#3b82f6' : '#94a3b8'};"><i data-lucide="git-branch"></i></div>
                        <span class="ui-card-title" style="font-size: 13px; font-weight: 700; color: ${isHead ? '#3b82f6' : '#f8fafc'}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${name}">${name}${isHead ? ' ✱' : ''}</span>
                    </div>
                    ${statusLine || (isHead ? '<span class="ui-badge" data-variant="success" style="font-size: 9px; padding: 1px 6px;">active</span>' : '')}
                </div>
                <div class="ui-card-body" style="padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; flex-grow: 1; justify-content: flex-end;">
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
                        ${behind > 0 ? `<button class="ui-button" data-variant="primary" data-size="sm" onclick="_gs2BranchAction('pull','${escapedName}','${escapedPath}', this)">↓ Pull</button>` : ''}
                        ${ahead > 0 ? `<button class="ui-button" data-variant="success" data-size="sm" onclick="_gs2BranchAction('push','${escapedName}','${escapedPath}', this)">↑ Push</button>` : ''}
                        <button class="ui-button" data-variant="outline" data-size="sm" onclick="_gs2BranchAction('fetch','${escapedName}','${escapedPath}', this)">Fetch</button>
                        <button class="ui-button" data-variant="secondary" data-size="sm" onclick="_gs2BranchAction('checkout','${escapedName}','${escapedPath}', this)">Check Out</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    return `
        <div style="margin-bottom: 24px;">
            <div class="ui-section-header" style="margin-bottom: 12px;">
                <h3 class="ui-section-title" style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: #f8fafc;">
                    <span>⚡ Pending Actions</span>
                    <span class="ui-badge" data-variant="warning" style="font-size: 10px;">${pending.length}</span>
                </h3>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px;">${cards}</div>
        </div>
    `;
}

/** Group branches by prefix folder dynamically */
function _gs2GroupBranches(branches) {
    const groups = {};
    const uncategorized = [];

    for (const b of branches) {
        const name = String(b.name || '');
        const slash = name.indexOf('/');
        if (slash > 0) {
            const prefix = name.substring(0, slash);
            const lowerPrefix = prefix.toLowerCase();
            if (!groups[lowerPrefix]) {
                groups[lowerPrefix] = {
                    key: lowerPrefix,
                    label: prefix + '/',
                    branches: []
                };
            }
            groups[lowerPrefix].branches.push(b);
        } else {
            uncategorized.push(b);
        }
    }

    const result = [];
    const sortedKeys = Object.keys(groups).sort();
    for (const key of sortedKeys) {
        result.push({
            label: groups[key].label.toUpperCase(),
            branches: groups[key].branches,
            colorKey: key
        });
    }

    if (uncategorized.length > 0) {
        result.push({
            label: 'STANDARD BRANCHES',
            branches: uncategorized,
            colorKey: 'standard'
        });
    }
    return result;
}

/** Build all categorized branch group sections */
function _gs2BuildGroupSections(rawPath, groups, head) {
    return groups.map(g => _gs2BuildGroup(rawPath, g, head)).join('');
}

/** Build one branch group section with full branch cards containing text buttons, nested by subfolders if applicable */
function _gs2BuildGroup(rawPath, group, head) {
    const colorMap = {
        feature: '#d69e2e', features: '#d69e2e',
        release: '#38b2ac', releases: '#38b2ac',
        hotfix: '#e53e3e', hotfixes: '#e53e3e',
        bugfix: '#b7791f', bugfixes: '#b7791f',
        po: '#bc72ff', standard: '#8ab4ff'
    };
    const color = colorMap[group.colorKey] || '#a8f0c6';

    // Group the branches under this top-level group by their second path segment
    const subGroups = {};
    const directBranches = [];

    for (const b of group.branches) {
        const name = String(b.name || '');
        const parts = name.split('/');
        if (parts.length > 2) {
            const isConfiguredApp = Array.isArray(_appsConfigCache) && _appsConfigCache.some(a => (a.id || '').toLowerCase() === subFolder.toLowerCase());
            if (isConfiguredApp && parts.length > 3) {
                subFolder = parts[2]; // Use version (e.g. "v1.1.2") instead of app prefix
            }
            if (!subGroups[subFolder]) subGroups[subFolder] = [];
            subGroups[subFolder].push(b);
        } else {
            directBranches.push(b);
        }
    }

    // Helper function to build cards list HTML using UI components
    const buildCardsHtml = (branchesList) => {
        return branchesList.map(b => {
            const name = escapeHtml(b.name || '');
            const behind = Number(b.behind || 0);
            const ahead  = Number(b.ahead  || 0);
            const isHead = b.name === head;
            const escapedName = (b.name || '').replace(/'/g, "\\'");
            const escapedPath = rawPath.replace(/'/g, "\\'");
            let badge = '';
            if (behind > 0 && ahead > 0) badge = `<span class="ui-badge" data-variant="warning">↑${ahead} ↓${behind}</span>`;
            else if (behind > 0) badge = `<span class="ui-badge" data-variant="primary">↓${behind} behind</span>`;
            else if (ahead > 0) badge = `<span class="ui-badge" data-variant="success">↑${ahead} ahead</span>`;

            return `
                <div class="ui-card" data-variant="interactive" data-branch-name="${name.toLowerCase()}" style="min-height: 120px; display: flex; flex-direction: column; justify-content: space-between; ${isHead ? 'border-color: #3b82f6; background: rgba(59, 130, 246, 0.1); box-shadow: 0 0 0 1px #3b82f6;' : ''}">
                    <div class="ui-card-header" style="padding: 10px 14px; background: transparent; border-bottom: none; display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;">
                        <div style="display: flex; align-items: flex-start; gap: 10px; min-width: 0; flex: 1;">
                            <div class="compact-app-card-icon" style="--app-color: ${isHead ? '#3b82f6' : '#94a3b8'};"><i data-lucide="git-branch"></i></div>
                            <span class="ui-card-title" style="font-size: 13px; font-weight: 700; color: ${isHead ? '#3b82f6' : '#f8fafc'}; white-space: normal; word-break: break-word; overflow-wrap: break-word; flex: 1;" title="${name}">${name}${isHead ? ' ✱' : ''}</span>
                        </div>
                        <div style="flex-shrink: 0; margin-top: 1px;">
                            ${badge || (isHead ? '<span class="ui-badge" data-variant="success" style="font-size: 9px; padding: 1px 6px;">active</span>' : '<span class="ui-badge" data-variant="neutral" style="font-size: 9px; padding: 1px 6px;">stable</span>')}
                        </div>
                    </div>
                    <div class="ui-card-body" style="padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; flex-grow: 1; justify-content: flex-end;">
                        <div style="display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
                            <button class="ui-button" data-variant="outline" data-size="sm" onclick="_gs2BranchAction('fetch','${escapedName}','${escapedPath}', this)">Fetch</button>
                            <button class="ui-button" data-variant="secondary" data-size="sm" onclick="_gs2BranchAction('checkout','${escapedName}','${escapedPath}', this)">Check Out</button>
                            ${behind > 0 ? `<button class="ui-button" data-variant="primary" data-size="sm" onclick="_gs2BranchAction('pull','${escapedName}','${escapedPath}', this)">↓ Pull</button>` : ''}
                            ${ahead > 0 ? `<button class="ui-button" data-variant="success" data-size="sm" onclick="_gs2BranchAction('push','${escapedName}','${escapedPath}', this)">↑ Push</button>` : ''}
                            <button class="ui-button" data-variant="outline" data-size="sm" onclick="openGitRenameBranchModal('${escapedPath}', '${escapedName}', this)">Rename</button>
                            <button class="ui-button" data-variant="outline" data-size="sm" onclick="openBranchCommitsScreen('${escapedName}','${escapedPath}', this)">Commits</button>
                            <button class="ui-button" data-variant="outline" data-size="sm" onclick="openGitMergeModal('${escapedPath}', '${escapedName}', this)">Merge</button>
                            <button class="ui-button" data-variant="danger" data-size="sm" ${isHead ? 'disabled' : ''} onclick="_gs2BranchDelete('${escapedName}','${escapedPath}', this)">Delete</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    };

    let innerHtml = '';

    // Render direct/un-nested branches first (if any)
    if (directBranches.length > 0) {
        innerHtml += `
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; margin-bottom: 16px;">
                ${buildCardsHtml(directBranches)}
            </div>
        `;
    }

    // Sort keys by version number descending if they look like version numbers, otherwise sort alphabetically descending.
    const compareSubFolders = (a, b) => {
        const clean = (s) => s.replace(/^v/i, '');
        const aClean = clean(a);
        const bClean = clean(b);

        const versionPattern = /^\d+(\.\d+)*$/;
        const isAVer = versionPattern.test(aClean);
        const isBVer = versionPattern.test(bClean);

        if (isAVer && isBVer) {
            const aParts = aClean.split('.').map(Number);
            const bParts = bClean.split('.').map(Number);
            const maxLen = Math.max(aParts.length, bParts.length);
            for (let i = 0; i < maxLen; i++) {
                const aVal = aParts[i] || 0;
                const bVal = bParts[i] || 0;
                if (aVal !== bVal) {
                    return bVal - aVal; // Descending (larger/latest first)
                }
            }
            return 0;
        }

        if (isAVer) return -1;
        if (isBVer) return 1;

        return b.localeCompare(a);
    };

    // Render subfolders (sorted latest/highest version first)
    const sortedSubFolders = Object.keys(subGroups).sort(compareSubFolders);
    for (const sub of sortedSubFolders) {
        const subBranches = subGroups[sub];
        innerHtml += `
            <div style="margin-left: 8px; margin-top: 14px; margin-bottom: 16px;">
                <div style="font-size: 12px; font-weight: 700; color: #a0aec0; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; text-transform: uppercase;">
                    <span>📂 ${escapeHtml(sub)}</span>
                    <span class="ui-badge" data-variant="neutral" style="font-size: 10px; padding: 1px 6px;">${subBranches.length}</span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px;">
                    ${buildCardsHtml(subBranches)}
                </div>
            </div>
        `;
    }

    return `
        <div style="margin-bottom: 28px;">
            <div class="ui-section-header" style="margin-top: 20px; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--ui-border-color, #1e293b); padding-bottom: 8px;">
                <h3 class="ui-section-title" style="display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: #f8fafc;">
                    <span style="color: ${color};">${escapeHtml(group.label)}</span>
                    <span class="ui-badge" data-variant="neutral" style="font-size: 11px;">${group.branches.length}</span>
                </h3>
            </div>
            ${innerHtml}
        </div>
    `;
}


/** Real-time branch search filter */
function _gs2FilterBranches(query) {
    const q = (query || '').toLowerCase().trim();
    const clearBtn = document.getElementById('gs2SearchClear');
    if (clearBtn) clearBtn.classList.toggle('hidden', !q);

    if (!q) {
        _gs2RenderBody(_gs2ActiveRepoPath, _gs2AllBranches,
            (_gitBranchStatusCache.get(_gs2ActiveRepoPath) || {}).head || '');
        return;
    }

    const filtered = _gs2AllBranches.filter(b => String(b.name || '').toLowerCase().includes(q));
    const data = _gitBranchStatusCache.get(_gs2ActiveRepoPath) || {};
    _gs2RenderBody(_gs2ActiveRepoPath, filtered, data.head || '');
}

/** Dispatch a branch-level git action from Screen 2 */
async function _gs2BranchAction(action, branchName, rawPath, btn) {
    if (action === 'checkout') {
        const card = btn ? btn.closest('.gs2-branch-card') : null;
        const isCurrentlyActive = card && card.querySelector('.gs2-head-branch');
        if (isCurrentlyActive) {
            const confirmSwitch = await window.showGitConfirm(
                "ℹ️ Branch Status Notice",
                `In the main application, you are already on the branch "${branchName}".\n\n` +
                `However, it is possible that some dependency packages are still checked out on different branches.\n\n` +
                `Would you like to run "Switch Again" to ensure all package repositories switch to the corresponding branch?`
            );
            if (!confirmSwitch) {
                return;
            }
        } else {
            const confirmCheckout = await window.showGitConfirm(
                "⌥ Checkout Branch",
                `Are you sure you want to check out and switch to branch "${branchName}"?`
            );
            if (!confirmCheckout) {
                return;
            }
        }
    }

    const useMelos = !!document.getElementById('gitGlobalUseMelos')?.checked;
    setGitStatus(`Running ${action} on ${branchName}…`);

    let originalText = '';
    if (btn) {
        originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...';
        btn.style.opacity = '0.6';
    }

    try {
        const resp = await fetch(apiUrl('/api/git/branch/action'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: rawPath,
                branch: branchName,
                action: action,
                useMelos: useMelos
            })
        });
        const data = await resp.json();

        if (data.prompt) {
            const createMissingMap = {};
            for (const repoName of data.missingRepos) {
                const create = confirm(
                    `Branch "${data.branch}" does not exist in repository "${repoName}".\n\n` +
                    `Would you like to create this branch in "${repoName}"?\n\n` +
                    `Click 'OK' (Yes) to create a new branch in "${repoName}".\n` +
                    `Click 'Cancel' (No) to skip and checkout fallback branch (e.g., 'develop') instead.`
                );
                createMissingMap[repoName] = create;
            }
            
            setGitStatus(`Applying choices…`);
            if (btn) {
                btn.disabled = true;
                btn.textContent = '...';
                btn.style.opacity = '0.6';
            }
            const resp2 = await fetch(apiUrl('/api/git/branch/action'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    repoPath: rawPath,
                    branch: branchName,
                    action: action,
                    useMelos: useMelos,
                    createMissingMap: createMissingMap
                })
            });
            const data2 = await resp2.json();
            if (data2.success) {
                setGitStatus(`✓ ${action} on ${branchName} complete`, 'success');
                _gitBranchStatusCache.delete(rawPath);
                await openRepoDetailScreen(rawPath, true);
            } else {
                setGitStatus(`⚠️ ${action} failed: ${data2.error || 'Unknown error'}`, 'error');
                alert(`⚠️ Action failed:\n\n${data2.error || 'Unknown error'}`);
            }
            return;
        }

        if (data.success) {
            setGitStatus(`✓ ${action} on ${branchName} complete`, 'success');
            // Refresh branch cache and re-render Screen 2 silently (retaining current view)
            _gitBranchStatusCache.delete(rawPath);
            await openRepoDetailScreen(rawPath, true);
        } else {
            setGitStatus(`⚠️ ${action} failed: ${data.error || 'Unknown error'}`, 'error');
            alert(`⚠️ Action failed:\n\n${data.error || 'Unknown error'}`);
        }
    } catch (err) {
        setGitStatus(`⚠️ ${action} error: ${err.message}`, 'error');
        alert(`❌ Network error:\n\n${err.message}`);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
            btn.style.opacity = '';
        }
    }
}

/** Delete a branch (locally and remote on origin) */
async function _gs2BranchDelete(branchName, rawPath, btn) {
    const useMelos = !!document.getElementById('gitGlobalUseMelos')?.checked;
    
    const confirmMsg = `Are you sure you want to delete branch '${branchName}'?\n\nThis will delete the branch locally (and push the deletion upstream to origin) across ${useMelos ? 'all repositories in Melos scope' : 'the repository'}.\n\nThis action cannot be undone.`;
    const confirmDelete = await window.showGitConfirm("✕ Delete Branch", confirmMsg);
    if (!confirmDelete) return;

    setGitStatus(`Deleting branch ${branchName}…`);

    let originalText = '';
    if (btn) {
        originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...';
        btn.style.opacity = '0.6';
    }

    try {
        const resp = await fetch(apiUrl('/api/git/branch/delete'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: rawPath,
                branchName: branchName,
                useMelos: useMelos
            })
        });
        const data = await resp.json();

        if (data.success) {
            setGitStatus(`✓ Deleted branch ${branchName} complete`, 'success');
            // Refresh branch cache and re-render Screen 2 silently
            _gitBranchStatusCache.delete(rawPath);
            await openRepoDetailScreen(rawPath, true);
            // Silently refresh Screen 1 cards (so branch count updates)
            if (typeof loadGitRepos === 'function') {
                loadGitRepos(true);
            }
        } else {
            setGitStatus(`⚠️ Deletion failed: ${data.error || 'Unknown error'}`, 'error');
            alert(`⚠️ Deletion failed:\n\n${data.error || 'Unknown error'}`);
        }
    } catch (err) {
        setGitStatus(`⚠️ Deletion error: ${err.message}`, 'error');
        alert(`❌ Network error:\n\n${err.message}`);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
            btn.style.opacity = '';
        }
    }
}

window._gs2BranchAction = _gs2BranchAction;
window._gs2BranchDelete = _gs2BranchDelete;

/** Wire up Screen 2 controls (back button + search) — called once on DOM ready */
function _initScreen2Controls() {
    const backBtn   = document.getElementById('gs2BackBtn');
    const searchEl  = document.getElementById('gs2SearchInput');
    const clearBtn  = document.getElementById('gs2SearchClear');
    const screen1   = document.getElementById('gitScreen1');
    const screen2   = document.getElementById('gitScreen2');

    if (backBtn) {
        backBtn.addEventListener('click', () => {
            screen2.classList.add('hidden');
            screen1.classList.remove('hidden');
            _gs2ActiveRepoPath = '';
            _gs2AllBranches = [];
            _gs2ActiveGroupKey = 'all';
        });
    }

    if (searchEl) {
        searchEl.addEventListener('input', (e) => _gs2FilterBranches(e.target.value));
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (searchEl) searchEl.value = '';
            _gs2FilterBranches('');
        });
    }
}

window.loadGitRepos = async function loadGitRepos(keepStatus = false, forceRefresh = false) {
    if (!keepStatus) {
        setGitStatus(forceRefresh ? 'Scanning workspace for new repos…' : 'Loading repos…');
        renderGitShimmers();
    }
    if (_appsConfigCache.length === 0) {
        try {
            const res = await fetch(apiUrl('/api/apps/config'));
            const data = await res.json();
            _appsConfigCache = data.apps || [];
        } catch (e) {
            console.error('Failed to load apps_config', e);
        }
    }
    const url = forceRefresh ? '/api/git/repos?refresh=true' : '/api/git/repos';
    fetch(apiUrl(url))
        .then((r) => r.json())
        .then(async (data) => {
            if (!data.success) throw new Error(data.error || 'Failed to load repos');
            const repos = Array.isArray(data.repos) ? data.repos : [];

            // If the user selected a different branch for a repo, fetch status for that branch
            // so badges reflect that selection.
            const patched = await Promise.all(repos.map(async (repo) => {
                const repoPath = String(repo.path || '');
                const chosen = _gitBranchChoices.get(repoPath);
                if (!chosen || !repoPath) return repo;
                if (String(repo.branch || '') === String(chosen)) return repo;
                try {
                    const status = await loadRepoStatus(repoPath, chosen);
                    // Preserve name/path; override computed fields.
                    return { ...repo, ...status, branch: chosen };
                } catch (_) {
                    return repo;
                }
            }));

            // Reconcile any persisted AI state that may be stuck (e.g. after server restart).
            // If we have a pending jobId but the server no longer knows it, clear the state.
            const now = Date.now();
            await Promise.all(patched.map(async (r) => {
                try {
                    const repoPath = String(r.path || '');
                    const branch = String(r.branch || '');
                    if (!repoPath || !branch) return;
                    const st = _getAiState(repoPath, branch);
                    if (!st) return;

                    const status = String(st.status || '');
                    if (status !== 'generating' && status !== 'committing') return;

                    const updatedAt = Number(st.updatedAt || 0);
                    const ageMs = updatedAt ? (now - updatedAt) : Number.POSITIVE_INFINITY;
                    // If older than 10 minutes, assume it's stale.
                    if (!Number.isFinite(ageMs) || ageMs > 10 * 60 * 1000) {
                        _clearAiState(repoPath, branch);
                        return;
                    }

                    const jobId = String(st.jobId || '').trim();
                    if (!jobId) {
                        _clearAiState(repoPath, branch);
                        return;
                    }

                    const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`));
                    const jd = await res.json();
                    if (!jd || !jd.success || !jd.job) {
                        _clearAiState(repoPath, branch);
                        return;
                    }
                    const job = jd.job;
                    const js = String(job.status || '');
                    if (js === 'running' || js === 'stopping') return;

                    // Finished jobs: update or clear state.
                    if (js === 'success' && job.result && job.result.message) {
                        _setAiState(repoPath, branch, { status: 'ready', jobId: '', message: String(job.result.message).trim(), committed: false });
                        return;
                    }
                    // Anything else becomes error (or clear).
                    const errText = String(job.error || job.output || 'AI job ended').trim();
                    _setAiState(repoPath, branch, { status: 'error', error: errText || 'AI job ended', jobId: '' });
                } catch (_) {
                    // If any error occurs reading job state, clear stuck state to avoid permanent "generating".
                    try {
                        const repoPath = String(r.path || '');
                        const branch = String(r.branch || '');
                        if (repoPath && branch) _clearAiState(repoPath, branch);
                    } catch (_) {}
                }
            }));

            // Clear stale "Commit message ready" state when repo is clean (after commit/push/fetch).
            for (const r of patched) {
                try {
                    const repoPath = String(r.path || '');
                    const branch = String(r.branch || '');
                    if (!repoPath || !branch) continue;
                    if (!!r.dirty) continue;
                    const st = _getAiState(repoPath, branch);
                    if (st && String(st.status || '') === 'ready') {
                        _clearAiState(repoPath, branch);
                    }
                } catch (_) {}
            }

            // Render cached data immediately so the page is fully loaded and responsive
            renderGitRepos(patched);
            if (!keepStatus) setGitStatus('Ready.');

            // Probe remote health in parallel in the background without blocking the UI
            Promise.all(patched.map(async (r) => {
                const repoPath = String(r.path || '');
                try {
                    const remoteHealth = repoPath ? await probeRemoteHealth(repoPath) : 'check';
                    return { ...r, remoteHealth };
                } catch (_) {
                    return { ...r, remoteHealth: 'check' };
                }
            })).then((enriched) => {
                // Check for new updates and notify
                enriched.forEach(repo => {
                    if (repo.behind > 0) {
                        const oldRepo = Array.isArray(_gitLastRenderedRepos) ? _gitLastRenderedRepos.find(x => x.path === repo.path) : null;
                        const oldBehind = oldRepo ? Number(oldRepo.behind || 0) : 0;
                        if (Number(repo.behind) > oldBehind) {
                            if ('Notification' in window && Notification.permission === 'granted') {
                                const rName = repo.name || (repo.path ? repo.path.split('/').pop() : 'Repo');
                                new Notification(`Git Update: ${rName}`, {
                                    body: `${repo.branch || 'Branch'} has ${repo.behind} new commit(s) to pull.`,
                                });
                            }
                        }
                    }
                });

                renderGitRepos(enriched);
                prefetchGitBranchInsights(enriched);
            }).catch(err => {
                console.error("Failed to load remote health checks in background:", err);
            });
        })
        .catch((e) => {
            renderGitRepos([]);
            setGitStatus(`Failed to load repos: ${e.message}`, 'error');
        });
}
function refreshSingleRepo(repoPath) {
    const branch = String(_gitBranchChoices.get(repoPath) || '');
    return loadRepoStatus(repoPath, branch).then((status) => {
        const card = document.querySelector(`.git-repo[data-repo-path-enc="${encodeURIComponent(repoPath)}"]`);
        if (!card) return loadGitRepos(true);
        const existing = Array.isArray(_gitLastRenderedRepos) ? _gitLastRenderedRepos.slice() : [];
        const idx = existing.findIndex((x) => String(x.path || '') === String(repoPath));
        if (idx >= 0) {
            existing[idx] = { ...existing[idx], ...status };
            _gitLastRenderedRepos = existing;
            renderGitRepos(existing);
        } else {
            loadGitRepos(true);
        }
    }).catch(() => loadGitRepos(true));
}
async function probeRemoteHealth(repoPath) {
    const cached = _gitBranchStatusCache.get(repoPath);
    if (cached && Array.isArray(cached.remoteBranches)) {
        return cached.remoteBranches.length
            ? { state: 'ok', cause: `found ${cached.remoteBranches.length} remote branch(es)` }
            : { state: 'check', cause: 'no remote branches found' };
    }
    return { state: 'ok', cause: 'remote check active' };
}

async function prefetchGitBranchInsights(repos) {
    if (_gitBranchPrefetchRunning) return;
    const repoList = Array.isArray(repos) ? repos : [];
    if (repoList.length === 0) return;
    _gitBranchPrefetchRunning = true;
    try {
        const pending = repoList
            .map((repo) => String(repo.path || ''))
            .filter((repoPath) => repoPath && !_gitBranchStatusCache.has(repoPath));
        for (const repoPath of pending) {
            try {
                const data = await loadRepoBranches(repoPath);
                _gitBranchStatusCache.set(repoPath, data);
                
                // Update the DOM for this repository dynamically without recreation
                const pathEnc = encodeURIComponent(repoPath);
                const card = document.querySelector(`.git-repo[data-repo-path-enc="${pathEnc}"]`);
                if (card) {
                    const sel = card.querySelector('select[data-action="branch-select"]');
                    if (sel && sel.dataset.loaded !== '1') {
                        populateSelectWithOptions(sel, repoPath, data);
                    }
                    // Only update insights drawer in Screen 2 detail view (containing .git-buttons-grid)
                    const grid = card.querySelector('.git-buttons-grid');
                    if (grid) {
                        let insightsDiv = card.querySelector('.git-behind-branches-box');
                        const insightsHtml = getBranchInsightsHtml(repoPath, data);
                        if (insightsHtml) {
                            if (insightsDiv) {
                                insightsDiv.outerHTML = insightsHtml;
                            } else {
                                grid.insertAdjacentHTML('beforebegin', insightsHtml);
                            }
                        } else if (insightsDiv) {
                            insightsDiv.remove();
                        }
                    }
                }
            } catch (_) {}
        }
    } finally {
        _gitBranchPrefetchRunning = false;
    }
}

function loadRepoBranches(repoPath, quick = false) {
    return fetch(apiUrl(`/api/git/branches?repoPath=${encodeURIComponent(repoPath)}&quick=${quick}`))
        .then((r) => r.json())
        .then((data) => {
            if (!data.success) throw new Error(data.error || 'Failed to load branches');
            return data;
        });
}

function loadRepoStatus(repoPath, branch) {
    const qs = `repoPath=${encodeURIComponent(repoPath)}&branch=${encodeURIComponent(branch || '')}`;
    return fetch(apiUrl(`/api/git/status?${qs}`))
        .then((r) => r.json())
        .then((data) => {
            if (!data.success) throw new Error(data.error || 'Failed to load status');
            return data.status;
        });
}

function getSelectOptionsHtml(repoPath, data) {
    const branches = Array.isArray(data.branches) ? data.branches : [];
    const branchStatuses = Array.isArray(data.branchStatuses) ? data.branchStatuses : [];
    const statusByName = new Map(branchStatuses.map((s) => [String(s.name || s.branch || ''), s]));
    const remoteBranches = Array.isArray(data.remoteBranches) ? data.remoteBranches : [];
    const head = String(data.head || '');
    const remembered = _gitBranchChoices.get(repoPath) || head;
    const scored = branches.map((b) => {
        const selected = (b === remembered) ? ' selected' : '';
        const st = statusByName.get(String(b));
        const behind = st && st.behind !== null && st.behind !== undefined ? Number(st.behind) : null;
        const ahead = st && st.ahead !== null && st.ahead !== undefined ? Number(st.ahead) : null;
        const hasUpstream = st ? st.hasUpstream !== false : true;
        let label = String(b);
        if (behind && behind > 0) label = `↓${behind}  ${label}`;
        if (ahead && ahead > 0) label = `↑${ahead}  ${label}`;
        if (st && st.hasUpstream === false) label = `(no-upstream)  ${label}`;
        const pri = (behind && behind > 0) ? 0 : (ahead && ahead > 0) ? 1 : 2;
        const behindScore = behind && behind > 0 ? behind : 0;
        const aheadScore = ahead && ahead > 0 ? ahead : 0;
        const score = pri * 1_000_000 - behindScore * 1000 - aheadScore;
        return {
            name: b,
            selected,
            label,
            pri,
            behindScore,
            aheadScore,
            hasUpstream,
            score,
        };
    });

    const ordered = scored.sort((a, b) => a.score - b.score || String(a.name).localeCompare(String(b.name)));

    const localOptions = ordered.map((x) => {
        let optionStyle = '';
        if (x.behindScore > 0) {
            optionStyle = ' style="color: #8ab4ff;"';
        } else if (x.aheadScore > 0) {
            optionStyle = ' style="color: #a8f0b6;"';
        } else if (x.hasUpstream === false) {
            optionStyle = ' style="color: #8ab4ff;"';
        }
        return `<option value="${escapeHtml(x.name)}"${x.selected}${optionStyle}>${escapeHtml(x.label)}</option>`;
    }).join('');

    const remoteOptions = remoteBranches.length
        ? (`<option value="" disabled>── remote ──</option>` +
           remoteBranches.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join(''))
        : `<option value="" disabled>── remote ──</option><option value="" disabled>(run Git Fetch to load remotes)</option>`;

    return (localOptions || `<option value="${escapeHtml(head)}">${escapeHtml(head || 'HEAD')}</option>`) + remoteOptions;
}

function populateSelectWithOptions(sel, repoPath, data) {
    const branchStatuses = Array.isArray(data.branchStatuses) ? data.branchStatuses : [];
    const statusByName = new Map(branchStatuses.map((s) => [String(s.name || s.branch || ''), s]));
    const head = String(data.head || '');
    const remembered = _gitBranchChoices.get(repoPath) || head;

    const activeSt = statusByName.get(String(remembered));
    const activeBehind = activeSt && activeSt.behind !== null && activeSt.behind !== undefined ? Number(activeSt.behind) : null;
    const activeAhead = activeSt && activeSt.ahead !== null && activeSt.ahead !== undefined ? Number(activeSt.ahead) : null;
    const activeHasUpstream = activeSt ? activeSt.hasUpstream !== false : true;

    if (activeBehind !== null && activeBehind > 0) {
        sel.style.setProperty('color', '#8ab4ff', 'important');
        sel.style.setProperty('border-color', 'rgba(138, 180, 255, 0.55)', 'important');
    } else if (activeAhead !== null && activeAhead > 0) {
        sel.style.setProperty('color', '#a8f0b6', 'important');
        sel.style.setProperty('border-color', 'rgba(40, 167, 69, 0.55)', 'important');
    } else if (!activeHasUpstream) {
        sel.style.setProperty('color', '#8ab4ff', 'important');
        sel.style.setProperty('border-color', 'rgba(138, 180, 255, 0.55)', 'important');
    } else {
        sel.style.setProperty('color', '#ffffff', 'important');
        sel.style.setProperty('border-color', 'rgba(255, 255, 255, 0.18)', 'important');
    }

    sel.innerHTML = getSelectOptionsHtml(repoPath, data);
    sel.dataset.loaded = '1';
}

function getBranchInsightsHtml(repoPath, data) {
    const branchStatuses = Array.isArray(data.branchStatuses) ? data.branchStatuses : [];
    const head = String(data.head || '');
    
    // Filter out branches that haven't been updated in the last 15 days
    const fifteenDaysAgo = (Date.now() / 1000) - (15 * 24 * 60 * 60);

    const branchNeedsPull = branchStatuses
        .map((b) => {
            const branchItemName = String(b.name || b.branch || '');
            const branchItemBehind = (b.behind === null || b.behind === undefined) ? 0 : Number(b.behind);
            const branchItemAhead = (b.ahead === null || b.ahead === undefined) ? 0 : Number(b.ahead);
            const branchItemUpdatedAt = Number(b.updatedAt || 0);
            const branchItemIsMerged = !!b.isMerged;
            return { branch: branchItemName, behind: branchItemBehind, ahead: branchItemAhead, isMerged: branchItemIsMerged, updatedAt: branchItemUpdatedAt };
        })
        .filter((b) => b.branch && b.behind > 0 && b.branch !== head && !b.isMerged && (!b.updatedAt || b.updatedAt >= fifteenDaysAgo))
        .sort((a, b) => b.behind - a.behind);

    if (branchNeedsPull.length > 0) {
        const branchRows = branchNeedsPull.map(b => {
            const bEsc = escapeHtml(b.branch);
            const hEsc = escapeHtml(head);
            return `
            <div class="git-behind-branch-row" title="${bEsc} is behind by ${b.behind} commit(s)">
                <div class="git-behind-branch-header">
                    <span class="git-behind-branch-icon">↓</span>
                    <span class="git-behind-branch-name" title="${bEsc}">${bEsc}</span>
                    <span class="git-behind-branch-badge">${b.behind} behind</span>
                </div>
                <div class="git-branch-actions-wrap">
                    <button class="api-btn small git-branch-action-btn pull" type="button" data-action="branch-action-pull" data-branch="${bEsc}" title="Pull remote updates: Run 'git pull' on local '${bEsc}' to download its ${b.behind} pending commits from origin.">
                        ↓ Pull Updates
                    </button>
                    <button class="api-btn small git-branch-action-btn merge-this" type="button" data-action="branch-action-merge-this" data-branch="${bEsc}" title="Integrate changes: Merge '${bEsc}' into your active branch (${hEsc}) to combine its ${b.behind} commits into your work.">
                        ← Integrate into ${hEsc}
                    </button>
                    <button class="api-btn small git-branch-action-btn" type="button" title="Rename this branch locally with optional remote update" onclick="openGitRenameBranchModal('${escapeHtml(repoPath)}', '${bEsc}', this); event.stopPropagation();" style="background: rgba(138, 180, 255, 0.08); border-color: rgba(138, 180, 255, 0.18); color: #8ab4ff;">
                        ⟲ Rename
                    </button>
                </div>
            </div>
            `;
        }).join('');
        return `
            <div class="git-behind-branches-box">
                <div class="git-behind-branches-title" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center;" onclick="this.parentElement.classList.toggle('collapsed')">
                    <span style="display:flex; align-items:center; gap: 6px; flex: 1; overflow: hidden;">
                        <span class="collapse-icon" style="display:inline-block; transition:transform 0.2s; font-size: 9px;">▼</span>
                        <span style="font-size: 9.5px; font-weight: 700; white-space: nowrap; letter-spacing: 0.5px; text-transform: uppercase;">Branch Updates</span>
                        <span class="git-behind-count badge-behind" style="font-size: 9px; padding: 2px 6px; white-space: nowrap;">${branchNeedsPull.length}</span>
                    </span>
                    <button class="api-btn sync-all-btn" type="button" data-action="branch-action-sync-all" title="Synchronize all fast-forwardable branches" onclick="event.stopPropagation();" style="width:auto; padding:3px 8px; font-size:9px; letter-spacing:0.5px; border-radius:4px; margin-left: 6px; background: rgba(138, 180, 255, 0.1); color: #8ab4ff; border: 1px solid rgba(138, 180, 255, 0.2); white-space: nowrap;">
                        SYNC ALL
                    </button>
                </div>
                <div class="git-behind-branches-content">
                    ${branchRows}
                </div>
            </div>
        `;
    }
    return '';
}

function startGitFetch(scope, repoPath = '', triggerBtn = null) {
    if (_gitFetchJobId) return;
    if (scope === 'one' && repoPath && _gitFetchRepoLocks.get(repoPath)) {
        if (_gitFetchJobId) {
            fetch(apiUrl('/api/job/stop'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobId: _gitFetchJobId }) })
                .then(() => setGitStatus('Stopping fetch…', null))
                .catch(() => {});
        }
        return;
    }
    setGitStatus('Fetching…');
    const fetchAllBtn = document.getElementById('gitFetchAllBtn');
    const refreshBtn = document.getElementById('gitRefreshBtn');
    const batchFetchBtn = document.getElementById('gitBatchFetchBtn');
    const batchUpdateBtn = document.getElementById('gitBatchUpdateBtn');
    const batchPushBtn = document.getElementById('gitBatchPushBtn');
    const fDirty = document.getElementById('gitFilterDirty');
    const fBehind = document.getElementById('gitFilterBehind');
    const fAhead = document.getElementById('gitFilterAhead');
    const fConflict = document.getElementById('gitFilterConflict');
    _gitFetchScope = String(scope || 'all');
    _gitFetchRepoPath = String(repoPath || '');
    const startedAt = Date.now();
    startGitFetch._startedAt = startedAt;
    if (_gitFetchScope === 'all') {
        if (fetchAllBtn) fetchAllBtn.classList.add('loading');
        if (refreshBtn) refreshBtn.classList.add('loading');
    } else if (triggerBtn) {
        triggerBtn.classList.add('loading');
        triggerBtn.disabled = true;
        triggerBtn.dataset.loading = '1';
        triggerBtn.dataset.originalText = triggerBtn.textContent || '⟳ Fetch';
        triggerBtn.textContent = 'Fetching…';
        _gitFetchRepoLocks.set(_gitFetchRepoPath, true);
        const row = triggerBtn.closest('.git-repo');
        if (row) row.querySelectorAll('button').forEach((b) => { if (b !== triggerBtn) b.disabled = true; });
    }

    fetch(apiUrl('/api/git/fetch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, repoPath }),
    })
        .then((r) => r.json())
        .then((data) => {
            if (!data.success || !data.jobId) throw new Error(data.error || 'Failed to start git fetch');
            _gitFetchJobId = data.jobId;
            pollGitFetchJob(_gitFetchJobId, startedAt);
        })
        .catch((e) => {
            _gitFetchJobId = null;
            if (_gitFetchScope === 'all') {
                if (fetchAllBtn) fetchAllBtn.classList.remove('loading');
                if (refreshBtn) refreshBtn.classList.remove('loading');
            } else if (triggerBtn) {
                triggerBtn.classList.remove('loading');
                triggerBtn.disabled = false;
                delete triggerBtn.dataset.loading;
                triggerBtn.textContent = triggerBtn.dataset.originalText || '⟳ Fetch';
                _gitFetchRepoLocks.delete(_gitFetchRepoPath);
                const row = triggerBtn.closest('.git-repo');
                if (row) row.querySelectorAll('button').forEach((b) => { b.disabled = false; });
            }
            setGitStatus(`Fetch failed: ${e.message}`, 'error');
        });
}

function pollGitFetchJob(jobId, startedAt = Date.now()) {
    fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`))
        .then((r) => r.json())
        .then((data) => {
            if (!data.success || !data.job) throw new Error(data.error || 'Failed to read job status');
            const job = data.job;
            if (job.status === 'running' || job.status === 'stopping') {
                setGitStatus('Fetching… (running)');
                setTimeout(() => pollGitFetchJob(jobId, startedAt), 900);
                return;
            }

            const fetchAllBtn = document.getElementById('gitFetchAllBtn');
            const refreshBtn = document.getElementById('gitRefreshBtn');
            if (_gitFetchScope === 'all') {
                if (fetchAllBtn) fetchAllBtn.classList.remove('loading');
                if (refreshBtn) refreshBtn.classList.remove('loading');
            } else {
                document.querySelectorAll('button[data-action="fetch-one"][data-loading="1"]').forEach((btn) => {
                    btn.classList.remove('loading');
                    btn.disabled = false;
                    delete btn.dataset.loading;
                    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
                    btn.textContent = `Done in ${elapsed}s`;
                    _pushGitHistory(_gitFetchRepoPath, 'fetch', true, Date.now() - startedAt);
                    setTimeout(() => { btn.textContent = btn.dataset.originalText || '⟳ Fetch'; }, 2200);
                    const row = btn.closest('.git-repo');
                    if (row) row.querySelectorAll('button').forEach((b) => { b.disabled = false; });
                });
                _gitFetchRepoLocks.delete(_gitFetchRepoPath);
            }

            _gitFetchJobId = null;
            if (job.status === 'success') {
                setGitStatus('Fetch complete.', 'success');
                loadGitRepos();
            } else {
                setGitStatus('Fetch failed. Check command output for details.', 'error');
                const details = [
                    job.error ? `--- stderr ---\n${job.error}` : '',
                    job.output ? `--- stdout ---\n${job.output}` : '',
                ].filter(Boolean).join('\n\n');
                showGitInfoModal('Fetch failed', `❌ FAILED: git fetch\n\n${details || ''}`.trim());
                loadGitRepos();
            }
        })
        .catch((e) => {
            const fetchAllBtn = document.getElementById('gitFetchAllBtn');
            const refreshBtn = document.getElementById('gitRefreshBtn');
            if (_gitFetchScope === 'all') {
                if (fetchAllBtn) fetchAllBtn.classList.remove('loading');
                if (refreshBtn) refreshBtn.classList.remove('loading');
            } else {
                document.querySelectorAll('button[data-action="fetch-one"][data-loading="1"]').forEach((btn) => {
                    btn.classList.remove('loading');
                    btn.disabled = false;
                    delete btn.dataset.loading;
                    btn.textContent = btn.dataset.originalText || '⟳ Fetch';
                    _pushGitHistory(_gitFetchRepoPath, 'fetch', false, Date.now() - startedAt);
                    const row = btn.closest('.git-repo');
                    if (row) row.querySelectorAll('button').forEach((b) => { b.disabled = false; });
                });
                _gitFetchRepoLocks.delete(_gitFetchRepoPath);
            }
            _gitFetchJobId = null;
            setGitStatus(`Fetch status error: ${e.message}`, 'error');
        });
}

function runGitPull(repoPath, btn) {
    const startedAt = Date.now();
    const safeMode = String((document.getElementById('gitSafeModeSelect')?.value || 'ff-only'));
    if (safeMode === 'merge') {
        const okMerge = confirm('Safe mode is merge. Proceed with potential merge update?');
        if (!okMerge) return;
    }
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Updating…';
    btn.style.opacity = '0.7';
    setGitStatus(`Pulling updates for ${PathBasename(repoPath)}…`);

    const globalMelos = document.getElementById('gitGlobalUseMelos');
    const useMelos = globalMelos ? globalMelos.checked : false;

    fetch(apiUrl('/api/git/pull'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath: repoPath, useMelos: useMelos, githubToken: localStorage.getItem('devgit_github_token_v1') || '' })
    })
    .then((r) => r.json())
    .then((data) => {
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        if (data.success) {
            _pushGitHistory(repoPath, 'pull', true, Date.now() - startedAt);
            _gitConflictRepos.delete(repoPath);
            setGitStatus(`Successfully updated ${PathBasename(repoPath)}!`, 'success');
            refreshSingleRepo(repoPath);
        } else {
            if (data.conflict) {
                _pushGitHistory(repoPath, 'pull', false, Date.now() - startedAt);
                _gitConflictRepos.set(repoPath, data.error || 'Merge conflict occurred.');
                setGitStatus(`Conflict detected in ${PathBasename(repoPath)}! Update aborted.`, 'error');
                if (confirm(`⚠️ Merge Conflict Detected!\n\n${data.error}\n\nWould you like to open the Conflict Resolution Assistant to resolve it now?`)) {
                    openConflictModal(repoPath);
                }
            } else {
                _pushGitHistory(repoPath, 'pull', false, Date.now() - startedAt);
                setGitStatus(`Update failed: ${data.error}`, 'error');
                if (window.handleGitflowError) {
                    window.handleGitflowError('Update Blocked', data.error);
                } else {
                    alert(`⚠️ Update Blocked:\n\n${data.error}`);
                }
            }
            refreshSingleRepo(repoPath);
        }
    })
    .catch((err) => {
        _pushGitHistory(repoPath, 'pull', false, Date.now() - startedAt);
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        setGitStatus(`Network error during update: ${err.message}`, 'error');
        alert(`❌ Network Error:\n\n${err.message}`);
    });
}

function isPushAllowed(repoPath, branchName) {
    let protectedBranches = _gitProtectedBranches;
    if (repoPath.includes('/packages/')) {
        protectedBranches = _gitProtectedBranches.filter(b => b !== 'main' && b !== 'master');
    }
    if (protectedBranches.includes(branchName)) {
        return confirm(`Branch "${branchName}" looks protected. Push anyway?`);
    }
    return true;
}

function runGitPush(repoPath, btn) {
    const startedAt = Date.now();
    const row = btn.closest('.git-repo');
    const branchSel = row ? row.querySelector('select[data-action="branch-select"]') : null;
    const branchName = String((branchSel && branchSel.value) || '');
    if (!isPushAllowed(repoPath, branchName)) return;

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Pushing…';
    btn.style.opacity = '0.7';
    setGitStatus(`Pushing ${PathBasename(repoPath)}…`);

    const globalMelos = document.getElementById('gitGlobalUseMelos');
    const useMelos = globalMelos ? globalMelos.checked : false;

    fetch(apiUrl('/api/git/push'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath: repoPath, useMelos: useMelos, githubToken: localStorage.getItem('devgit_github_token_v1') || '' })
    })
    .then((r) => r.json())
    .then((data) => {
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        if (data.success) {
            _pushGitHistory(repoPath, 'push', true, Date.now() - startedAt);
            setGitStatus(`Pushed ${PathBasename(repoPath)} successfully!`, 'success');
            refreshSingleRepo(repoPath);
        } else {
            _pushGitHistory(repoPath, 'push', false, Date.now() - startedAt);
            setGitStatus(`Push failed: ${data.error}`, 'error');
            if (window.handleGitflowError) {
                window.handleGitflowError('Push Blocked', data.error);
            } else {
                alert(`⚠️ Push Blocked:\n\n${data.error}`);
            }
            refreshSingleRepo(repoPath);
        }
    })
    .catch((e) => {
        _pushGitHistory(repoPath, 'push', false, Date.now() - startedAt);
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        setGitStatus(`Push error: ${e.message}`, 'error');
    });
}

async function runBatchAction(action) {
    const rows = Array.from(document.querySelectorAll('.git-repo input[data-action="batch-select"]:checked'))
        .map((cb) => cb.closest('.git-repo'))
        .filter(Boolean);
    if (!rows.length) {
        setGitStatus('No repos selected for batch action.', 'error');
        return;
    }
    setGitStatus(`Running batch ${action} on ${rows.length} repo(s)…`);
    const summary = { success: 0, failed: 0, skipped: 0, lines: [] };
    for (const row of rows) {
        const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
        if (!repoPath) { summary.skipped += 1; continue; }
        const btn = row.querySelector(`button[data-action="${action}-one"]`);
        if (!btn || btn.disabled) {
            summary.skipped += 1;
            summary.lines.push(`${PathBasename(repoPath)}: skipped (action unavailable)`);
            continue;
        }
        const before = String(btn.textContent || '');
        btn.click();
        await new Promise((resolve) => setTimeout(resolve, 250));
        const after = String(btn.textContent || '');
        if (after.toLowerCase().includes('failed')) {
            summary.failed += 1;
            summary.lines.push(`${PathBasename(repoPath)}: failed`);
        } else {
            summary.success += 1;
            summary.lines.push(`${PathBasename(repoPath)}: queued`);
        }
    }
    const body = [
        `Batch ${action} summary`,
        `success: ${summary.success}`,
        `failed: ${summary.failed}`,
        `skipped: ${summary.skipped}`,
        '',
        ...summary.lines,
    ].join('\n');
    showGitInfoModal(`Batch ${action} summary`, body);
}
async function runGitStashPullPop(repoPath, btn) {
    const originalText = btn.textContent;
    const startedAt = Date.now();
    btn.disabled = true;
    btn.textContent = 'Running…';
    try {
        const res = await fetch(apiUrl('/api/git/stash-pull-pop'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath: repoPath })
        });
        const data = await res.json();
        if (!data.success) {
            throw new Error(data.error || 'Stash+Pull+Pop failed');
        }
        _pushGitHistory(repoPath, 'stash-pull-pop', true, Date.now() - startedAt);
        setGitStatus(`Stash+Pull+Pop done for ${PathBasename(repoPath)}`, 'success');
        refreshSingleRepo(repoPath);
    } catch (err) {
        _pushGitHistory(repoPath, 'stash-pull-pop', false, Date.now() - startedAt);
        setGitStatus(`Stash+Pull+Pop failed for ${PathBasename(repoPath)}: ${err.message}`, 'error');
        alert(`⚠️ Stash+Pull+Pop Failed:\n\n${err.message}`);
        refreshSingleRepo(repoPath);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function runGitSyncAll(repoPath, btn) {
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '...';
    btn.style.opacity = '0.7';
    setGitStatus(`Synchronizing remote branches for ${PathBasename(repoPath)}…`);

    fetch(apiUrl('/api/git/sync-all-branches'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath: repoPath })
    })
        .then(res => res.json())
        .then(data => {
            btn.disabled = false;
            btn.textContent = originalText;
            btn.style.opacity = '';
            if (data.success) {
                setGitStatus(data.message || `Successfully synchronized branches for ${PathBasename(repoPath)}.`, 'success');
                _gitBranchStatusCache.delete(repoPath);
                loadGitRepos(true); 
            } else {
                setGitStatus(`Sync error: ${data.error}`, 'error');
            }
        })
        .catch((e) => {
            btn.disabled = false;
            btn.textContent = originalText;
            btn.style.opacity = '';
            setGitStatus(`Sync error: ${e.message}`, 'error');
        });
}

function runGitBranchAction(repoPath, branch, action, btn) {
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '...';
    btn.style.opacity = '0.7';
    setGitStatus(`Running branch action '${action}' for ${PathBasename(repoPath)}:${branch}…`);

    const globalMelos = document.getElementById('gitGlobalUseMelos');
    const useMelos = globalMelos ? globalMelos.checked : false;

    fetch(apiUrl('/api/git/branch/action'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repoPath, branch, action, useMelos })
    })
    .then((r) => r.json())
    .then(async (data) => {
        if (data.prompt) {
            const createMissingMap = {};
            for (const repoName of data.missingRepos) {
                const create = confirm(
                    `Branch "${data.branch}" does not exist in repository "${repoName}".\n\n` +
                    `Would you like to create this branch in "${repoName}"?\n\n` +
                    `Click 'OK' (Yes) to create a new branch in "${repoName}".\n` +
                    `Click 'Cancel' (No) to skip and checkout fallback branch (e.g., 'develop') instead.`
                );
                createMissingMap[repoName] = create;
            }
            
            setGitStatus(`Applying choices…`);
            btn.disabled = true;
            btn.textContent = '...';
            btn.style.opacity = '0.7';
            try {
                const resp2 = await fetch(apiUrl('/api/git/branch/action'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ repoPath, branch, action, useMelos, createMissingMap })
                });
                const data2 = await resp2.json();
                btn.disabled = false;
                btn.textContent = originalText;
                btn.style.opacity = '';
                if (data2.success) {
                    setGitStatus(`Success: ${data2.message || 'Action completed successfully.'}`, 'success');
                    loadGitRepos();
                } else {
                    setGitStatus(`Action failed: ${data2.error}`, 'error');
                    alert(`⚠️ Action Blocked:\n\n${data2.error}`);
                    loadGitRepos(true);
                }
            } catch (err) {
                btn.disabled = false;
                btn.textContent = originalText;
                btn.style.opacity = '';
                setGitStatus(`Network error: ${err.message}`, 'error');
                alert(`❌ Network Error:\n\n${err.message}`);
            }
            return;
        }

        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        if (data.success) {
            setGitStatus(`Success: ${data.message || 'Action completed successfully.'}`, 'success');
            loadGitRepos();
        } else {
            if (data.conflict) {
                setGitStatus(`Conflict detected during branch action! Merging aborted.`, 'error');
                if (confirm(`⚠️ Merge Conflict Detected!\n\n${data.error || 'A merge conflict occurred.'}\n\nWould you like to open the Conflict Resolution Assistant to resolve it now?`)) {
                    openConflictModal(repoPath);
                }
            } else {
                setGitStatus(`Action failed: ${data.error}`, 'error');
                alert(`⚠️ Action Blocked:\n\n${data.error}`);
            }
            loadGitRepos(true);
        }
    })
    .catch((err) => {
        btn.disabled = false;
        btn.textContent = originalText;
        btn.style.opacity = '';
        setGitStatus(`Network error: ${err.message}`, 'error');
        alert(`❌ Network Error:\n\n${err.message}`);
    });
}

function openGitRenameBranchModal(repoPath, branch, btn) {
    const modal = document.getElementById('gitRenameBranchModal');
    const oldInput = document.getElementById('gitRenameOldBranch');
    const newInput = document.getElementById('gitRenameNewBranch');
    const remoteCb = document.getElementById('gitRenameRemoteBranch');
    const useMelosCb = document.getElementById('gitRenameUseMelos');
    const previewEl = document.getElementById('gitRenameBranchPreview');
    const submitBtn = document.getElementById('gitRenameBranchSubmit');
    const closeBtn = document.getElementById('gitRenameBranchClose');
    const cancelBtn = document.getElementById('gitRenameBranchCancel');
    if (!modal || !oldInput || !newInput || !remoteCb || !useMelosCb || !submitBtn || !previewEl) return;

    oldInput.value = branch;
    newInput.value = branch;
    remoteCb.checked = false;
    const globalMelos = document.getElementById('gitGlobalUseMelos');
    useMelosCb.checked = globalMelos ? globalMelos.checked : true;
    const renderPreview = () => {
        const oldBranch = String(oldInput.value || '').trim() || 'old-branch';
        const newBranch = String(newInput.value || '').trim() || 'new-branch';
        const remote = remoteCb.checked ? ' --remote' : '';
        previewEl.textContent = `melos run git:rename_branch:all -- ${oldBranch} ${newBranch}${remote}`;
    };
    modal.classList.remove('hidden');
    setTimeout(() => newInput.focus(), 0);
    renderPreview();

    const cleanup = () => {
        document.removeEventListener('keydown', onKeyDown);
        newInput.removeEventListener('input', renderPreview);
        remoteCb.removeEventListener('change', renderPreview);
        useMelosCb.removeEventListener('change', renderPreview);
    };
    const close = () => {
        modal.classList.add('hidden');
        cleanup();
        submitBtn.onclick = null;
        if (closeBtn) closeBtn.onclick = null;
        if (cancelBtn) cancelBtn.onclick = null;
        modal.onclick = null;
    };
    const onKeyDown = (e) => {
        if (e.key === 'Escape') close();
        if (e.key === 'Enter') {
            e.preventDefault();
            submitBtn.click();
        }
    };

    newInput.addEventListener('input', renderPreview);
    remoteCb.addEventListener('change', renderPreview);
    useMelosCb.addEventListener('change', renderPreview);

    submitBtn.onclick = async () => {
        const newBranch = String(newInput.value || '').trim();
        if (!newBranch) {
            alert('❌ New branch name is empty');
            return;
        }
        submitBtn.disabled = true;
        submitBtn.textContent = 'Renaming...';
        try {
            const res = await fetch(apiUrl('/api/git/branch/action'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    repoPath,
                    branch,
                    action: 'rename',
                    newBranch,
                    remote: remoteCb.checked,
                    useMelos: useMelosCb.checked,
                    githubToken: localStorage.getItem('devgit_github_token_v1') || ''
                })
            });
            const data = await res.json();
            if (!data.success) {
                if (window.handleGitflowError) {
                    window.handleGitflowError('Rename failed', data.error || 'Unknown error');
                } else {
                    alert(`⚠️ Rename failed:\n\n${data.error || 'Unknown error'}`);
                }
                return;
            }
            setGitStatus(`Success: ${data.message || 'Branch renamed.'}`, 'success');
            close();
            _gitBranchStatusCache.delete(repoPath);
            await openRepoDetailScreen(repoPath, true);
            loadGitRepos(true);
        } catch (err) {
            alert(`❌ Network Error:\n\n${err.message}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Rename Branch';
        }
    };

    if (closeBtn) closeBtn.onclick = close;
    if (cancelBtn) cancelBtn.onclick = close;
    modal.onclick = (e) => { if (e.target === modal) close(); };
    document.addEventListener('keydown', onKeyDown);
}

let _gitCommitsCache = [];

function _renderGitCommitRow(c) {
    const stats = (c.filesChanged > 0)
        ? `<span title="${c.filesChanged} file${c.filesChanged === 1 ? '' : 's'} changed" style="display:inline-flex; align-items:center; gap:6px; font-family:'JetBrains Mono', monospace; font-size:10.5px; flex-shrink:0;">
                <span style="color:#4ade80;">+${c.insertions}</span><span style="color:#f87171;">-${c.deletions}</span>
           </span>`
        : '';
    const githubLink = c.webUrl
        ? `<a href="${escapeHtml(c.webUrl)}" target="_blank" rel="noopener noreferrer" title="View commit on GitHub" aria-label="View commit on GitHub" data-action="view-commit-remote" style="display:inline-flex; align-items:center; color:#94a3b8; flex-shrink:0;"><i data-lucide="external-link" style="width:13px; height:13px;"></i></a>`
        : '';

    return `
        <div class="ui-card commit-item" data-full-sha="${escapeHtml(c.fullSha || c.sha)}" style="flex-shrink: 0; padding: 10px 12px; margin-bottom: 8px; border-color: #1e293b; display: flex; flex-direction: column; gap: 6px;">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 11px;">
                <div style="display:flex; align-items:center; gap: 6px; min-width:0;">
                    <span class="ui-badge" data-variant="primary" title="${escapeHtml(c.fullSha || c.sha)}" style="font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; text-transform: none; user-select: text; cursor: text;">${escapeHtml(c.sha)}</span>
                    <button type="button" class="git-commit-copy-btn" data-action="copy-commit-sha" data-sha="${escapeHtml(c.fullSha || c.sha)}" title="Copy full commit hash" aria-label="Copy full commit hash" style="background:transparent; border:none; color:#64748b; cursor:pointer; display:inline-flex; align-items:center; padding:2px; flex-shrink:0;">
                        <i data-lucide="copy" style="width:13px; height:13px;"></i>
                    </button>
                    ${githubLink}
                </div>
                <div style="display:flex; align-items:center; gap:10px; flex-shrink:0;">
                    ${stats}
                    <span title="${escapeHtml(c.dateAbsolute || c.date)}" style="color: #94a3b8;">${escapeHtml(c.date)}</span>
                </div>
            </div>
            <div style="font-size: 13px; font-weight: 500; line-height: 1.4; color: #e2e8f0; word-break: break-word; user-select: text;">${escapeHtml(c.message)}</div>
            <div style="font-size: 11px; color: #94a3b8; text-align: right; font-style: italic;">— ${escapeHtml(c.author)}</div>
        </div>
    `;
}

function _filterGitCommits(query) {
    const listEl = document.getElementById('gitCommitsList');
    const emptyEl = document.getElementById('gitCommitsEmpty');
    if (!listEl) return;

    const q = (query || '').trim().toLowerCase();
    const filtered = q
        ? _gitCommitsCache.filter(c =>
            (c.message || '').toLowerCase().includes(q) ||
            (c.author || '').toLowerCase().includes(q) ||
            (c.sha || '').toLowerCase().includes(q) ||
            (c.fullSha || '').toLowerCase().includes(q))
        : _gitCommitsCache;

    if (filtered.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');
    listEl.innerHTML = filtered.map(_renderGitCommitRow).join('');
    if (window.lucide) window.lucide.createIcons();
}

async function openBranchCommitsScreen(branchName, repoPath, btn) {
    const modal = document.getElementById('gitCommitsModal');
    const titleEl = document.getElementById('gitCommitsModalTitle');
    const loadingEl = document.getElementById('gitCommitsLoading');
    const listEl = document.getElementById('gitCommitsList');
    const emptyEl = document.getElementById('gitCommitsEmpty');
    const searchEl = document.getElementById('gitCommitsSearchInput');

    if (!modal || !listEl || !loadingEl) return;

    if (titleEl) {
        titleEl.textContent = `🕒 Commit History: ${branchName} (${repoPath.split('/').pop()})`;
    }

    let originalText = '';
    if (btn) {
        originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...';
        btn.style.opacity = '0.6';
    }

    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    loadingEl.style.display = 'block';
    if (emptyEl) emptyEl.classList.add('hidden');
    if (searchEl) { searchEl.style.display = 'none'; searchEl.value = ''; }
    listEl.innerHTML = '';
    _gitCommitsCache = [];

    try {
        const resp = await fetch(apiUrl(`/api/git/commits?repoPath=${encodeURIComponent(repoPath)}&branch=${encodeURIComponent(branchName)}`));
        const data = await resp.json();

        loadingEl.style.display = 'none';

        if (!data.success) {
            listEl.innerHTML = `<div style="color: #f85149; text-align: center; padding: 20px;">⚠️ ${escapeHtml(data.error || 'Failed to load commits')}</div>`;
            return;
        }

        const commits = data.commits || [];
        if (commits.length === 0) {
            listEl.innerHTML = `<div style="color: #8b949e; text-align: center; padding: 20px;">No commits found on this branch.</div>`;
            return;
        }

        _gitCommitsCache = commits;
        if (searchEl) searchEl.style.display = commits.length > 5 ? 'block' : 'none';
        listEl.innerHTML = commits.map(_renderGitCommitRow).join('');
        if (window.lucide) window.lucide.createIcons();

    } catch (err) {
        loadingEl.style.display = 'none';
        listEl.innerHTML = `<div style="color: #f85149; text-align: center; padding: 20px;">⚠️ Error: ${escapeHtml(err.message || err)}</div>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
            btn.style.opacity = '';
        }
    }
}

function closeGitCommitsModal() {
    const modal = document.getElementById('gitCommitsModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.style.display = 'none';
    }
    _gitCommitsCache = [];
}

/**
 * A searchable branch picker: collapses to a pill showing the current selection with a ✕ to
 * change it; clicking the pill (or ✕) opens a filterable, scrollable branch list in its place.
 * Selecting an item re-collapses it. Clicking outside closes it back to the pill.
 *
 * opts: { container, branches: string[], initialValue: string, excludeGetter?: () => string, onSelect?: (value) => void }
 * Returns { getValue, setValue, refreshExclusion, destroy }.
 */
function _createGitBranchPicker(opts) {
    const { container } = opts;
    const branches = opts.branches || [];
    let value = opts.initialValue || '';
    let isOpen = false;

    const renderClosed = () => {
        isOpen = false;
        container.innerHTML = `
            <div class="git-branch-picker-pill" tabindex="0" role="button" aria-haspopup="listbox"
                style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:9px 12px; border:1px solid var(--ui-border-color, #334155); border-radius:8px; background:var(--ui-bg-muted, #1e293b); cursor:pointer;">
                <span style="display:flex; align-items:center; gap:8px; min-width:0; color:${value ? '#60a5fa' : '#64748b'}; font-weight:600; font-size:13px;">
                    <i data-lucide="git-branch" style="width:14px; height:14px; flex-shrink:0;"></i>
                    <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${value ? escapeHtml(value) : 'Select a branch…'}</span>
                </span>
                <button type="button" class="git-branch-picker-clear" title="Change branch" aria-label="Change branch"
                    style="background:transparent; border:none; color:#94a3b8; cursor:pointer; display:inline-flex; padding:2px; flex-shrink:0;">
                    <i data-lucide="x" style="width:14px; height:14px;"></i>
                </button>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        const pill = container.querySelector('.git-branch-picker-pill');
        pill.addEventListener('click', (e) => {
            if (e.target.closest('.git-branch-picker-clear')) return;
            renderOpen();
        });
        pill.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); renderOpen(); }
        });
        container.querySelector('.git-branch-picker-clear').addEventListener('click', (e) => {
            e.stopPropagation();
            renderOpen();
        });
    };

    const renderOpen = () => {
        isOpen = true;
        const excluded = opts.excludeGetter ? opts.excludeGetter() : '';
        container.innerHTML = `
            <input type="text" class="ui-input git-branch-picker-search" placeholder="Search branches…" autocomplete="off" style="width:100%;" />
            <div class="git-branch-picker-list" role="listbox" style="margin-top:6px; max-height:200px; overflow-y:auto; border:1px solid var(--ui-border-color, #334155); border-radius:8px; background:var(--ui-bg-muted, #1e293b);"></div>
        `;
        const searchInput = container.querySelector('.git-branch-picker-search');
        const listEl = container.querySelector('.git-branch-picker-list');

        const renderList = (query) => {
            const q = (query || '').toLowerCase().trim();
            const matches = branches.filter(b => b !== excluded && (!q || b.toLowerCase().includes(q)));
            if (matches.length === 0) {
                listEl.innerHTML = `<div style="padding:14px; text-align:center; color:#64748b; font-size:12px;">No matching branches.</div>`;
                return;
            }
            listEl.innerHTML = `
                <div style="padding:6px 12px 4px; font-size:10px; font-weight:700; letter-spacing:0.5px; color:#64748b; text-transform:uppercase;">Branches</div>
                ${matches.map(b => `
                    <div class="git-branch-picker-item" data-branch="${escapeHtml(b)}" role="option" aria-selected="${b === value}"
                        style="display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 12px; cursor:pointer; font-size:13px; color:${b === value ? '#60a5fa' : '#e2e8f0'}; ${b === value ? 'background:rgba(59,130,246,0.1);' : ''}">
                        <span style="display:flex; align-items:center; gap:8px; min-width:0; overflow:hidden;">
                            <i data-lucide="git-branch" style="width:13px; height:13px; flex-shrink:0;"></i>
                            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(b)}</span>
                        </span>
                        ${b === value ? '<i data-lucide="check" style="width:14px; height:14px; flex-shrink:0;"></i>' : ''}
                    </div>
                `).join('')}
            `;
            if (window.lucide) window.lucide.createIcons();
            listEl.querySelectorAll('.git-branch-picker-item').forEach(item => {
                item.addEventListener('mouseenter', () => { if (item.getAttribute('data-branch') !== value) item.style.background = 'rgba(255,255,255,0.05)'; });
                item.addEventListener('mouseleave', () => { if (item.getAttribute('data-branch') !== value) item.style.background = ''; });
                item.addEventListener('click', () => {
                    value = item.getAttribute('data-branch');
                    renderClosed();
                    if (opts.onSelect) opts.onSelect(value);
                });
            });
        };

        renderList('');
        searchInput.addEventListener('input', (e) => renderList(e.target.value));
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { e.preventDefault(); renderClosed(); }
        });
        setTimeout(() => searchInput.focus(), 0);
    };

    const onDocClick = (e) => {
        if (isOpen && !container.contains(e.target)) renderClosed();
    };
    document.addEventListener('click', onDocClick, true);

    renderClosed();

    return {
        getValue: () => value,
        setValue: (v) => { value = v || ''; renderClosed(); },
        refreshExclusion: () => { if (isOpen) renderOpen(); },
        destroy: () => document.removeEventListener('click', onDocClick, true),
    };
}

let _gitMergeSourcePicker = null;
let _gitMergeTargetPicker = null;

function openGitMergeModal(repoPath, branch, btn) {
    const modal = document.getElementById('gitMergeModal');
    const sourceField = document.getElementById('gitMergeSourceField');
    const targetField = document.getElementById('gitMergeTargetField');
    const useMelosCb = document.getElementById('gitMergeUseMelos');
    const submitBtn = document.getElementById('gitMergeSubmit');
    const closeBtn = document.getElementById('gitMergeModalClose');
    const cancelBtn = document.getElementById('gitMergeCancel');
    const swapBtn = document.getElementById('gitMergeSwapBtn');

    if (!modal || !sourceField || !targetField || !useMelosCb || !submitBtn) return;

    const allBranchNames = _gs2AllBranches.map(b => b.name);
    const priority = ['develop', 'main', 'master', 'production', 'release'];
    const sortedBranches = [...allBranchNames].sort((x, y) => {
        const idxX = priority.indexOf(x);
        const idxY = priority.indexOf(y);
        if (idxX !== -1 && idxY !== -1) return idxX - idxY;
        if (idxX !== -1) return -1;
        if (idxY !== -1) return 1;
        return x.localeCompare(y);
    });
    const defaultTarget = sortedBranches.find(name => name !== branch) || '';

    if (_gitMergeSourcePicker) _gitMergeSourcePicker.destroy();
    if (_gitMergeTargetPicker) _gitMergeTargetPicker.destroy();

    _gitMergeSourcePicker = _createGitBranchPicker({
        container: sourceField,
        branches: sortedBranches,
        initialValue: branch,
        excludeGetter: () => _gitMergeTargetPicker ? _gitMergeTargetPicker.getValue() : '',
        onSelect: () => { if (_gitMergeTargetPicker) _gitMergeTargetPicker.refreshExclusion(); },
    });
    _gitMergeTargetPicker = _createGitBranchPicker({
        container: targetField,
        branches: sortedBranches,
        initialValue: defaultTarget,
        excludeGetter: () => _gitMergeSourcePicker ? _gitMergeSourcePicker.getValue() : '',
        onSelect: () => { if (_gitMergeSourcePicker) _gitMergeSourcePicker.refreshExclusion(); },
    });

    const globalMelos = document.getElementById('gitGlobalUseMelos');
    useMelosCb.checked = globalMelos ? globalMelos.checked : true;

    modal.classList.remove('hidden');
    modal.style.display = 'flex';

    const close = () => {
        modal.classList.add('hidden');
        modal.style.display = 'none';
        submitBtn.onclick = null;
        if (closeBtn) closeBtn.onclick = null;
        if (cancelBtn) cancelBtn.onclick = null;
        modal.onclick = null;
        if (swapBtn) swapBtn.onclick = null;
        if (_gitMergeSourcePicker) { _gitMergeSourcePicker.destroy(); _gitMergeSourcePicker = null; }
        if (_gitMergeTargetPicker) { _gitMergeTargetPicker.destroy(); _gitMergeTargetPicker = null; }
    };

    if (swapBtn) swapBtn.onclick = () => {
        if (!_gitMergeSourcePicker || !_gitMergeTargetPicker) return;
        const sourceVal = _gitMergeSourcePicker.getValue();
        const targetVal = _gitMergeTargetPicker.getValue();
        _gitMergeSourcePicker.setValue(targetVal);
        _gitMergeTargetPicker.setValue(sourceVal);
        swapBtn.style.transform = 'rotate(180deg)';
        setTimeout(() => { swapBtn.style.transform = ''; }, 200);
    };

    submitBtn.onclick = async () => {
        const sourceBranch = _gitMergeSourcePicker.getValue();
        const targetBranch = _gitMergeTargetPicker.getValue();
        if (!sourceBranch || !targetBranch) {
            alert('❌ Please select both a source and target branch.');
            return;
        }
        if (sourceBranch === targetBranch) {
            alert('❌ Source and target branch must be different.');
            return;
        }

        let originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Merging...';

        try {
            const res = await fetch(apiUrl('/api/git/branch/action'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    repoPath,
                    branch: sourceBranch,
                    action: 'merge',
                    targetBranch,
                    useMelos: useMelosCb.checked
                })
            });
            const data = await res.json();
            if (!data.success) {
                alert(`⚠️ Merge failed:\n\n${data.error || 'Unknown error'}`);
                return;
            }
            setGitStatus(`Success: ${data.message || 'Branch merged.'}`, 'success');
            close();
            
            if (data.noOpWarnings && data.noOpWarnings.length > 0) {
                const mergedRepos = data.mergedRepos || [];
                const noOpRepos = data.noOpRepos || [];

                const mergedSection = mergedRepos.length > 0
                    ? mergedRepos.map(name => `  • ${name}`).join('\n')
                    : '  (none — every repository in scope was already up to date)';

                const noOpSection = noOpRepos.length > 0
                    ? noOpRepos.map((name, i) => `  • ${name}\n    ${(data.noOpWarnings[i] || '').replace(/\n/g, '\n    ')}`).join('\n\n')
                    : '  (none)';

                const warningMsg =
                    `✅ Merged — new changes applied (${mergedRepos.length}):\n${mergedSection}\n\n` +
                    `ℹ️ Already up to date — no changes to apply (${noOpRepos.length}):\n${noOpSection}`;

                window.showGitAlert("ℹ️ Git Merge Info (Already Merged)", warningMsg);
            }

            _gitBranchStatusCache.delete(repoPath);
            await openRepoDetailScreen(repoPath, true);
            loadGitRepos(true);
        } catch (err) {
            alert(`❌ Network Error:\n\n${err.message}`);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    };

    if (closeBtn) closeBtn.onclick = close;
    if (cancelBtn) cancelBtn.onclick = close;
    modal.onclick = (e) => { if (e.target === modal) close(); };
}

// Wire up buttons
(() => {
    const fetchAllBtn = document.getElementById('gitFetchAllBtn');
    const refreshReposBtn = document.getElementById('gitRefreshReposBtn');
    const refreshBtn = document.getElementById('gitRefreshBtn');
    const batchFetchBtn = document.getElementById('gitBatchFetchBtn');
    const batchUpdateBtn = document.getElementById('gitBatchUpdateBtn');
    const batchPushBtn = document.getElementById('gitBatchPushBtn');
    const fDirty = document.getElementById('gitFilterDirty');
    const fBehind = document.getElementById('gitFilterBehind');
    const fAhead = document.getElementById('gitFilterAhead');
    const fConflict = document.getElementById('gitFilterConflict');
    const repoListApps = document.getElementById('gitRepoListApps');
    const repoListPackages = document.getElementById('gitRepoListPackages');
    const gitInfoModalClose = document.getElementById('gitInfoModalClose');
    const gitInfoModalCopy = document.getElementById('gitInfoModalCopy');
    const gitInfoModal = document.getElementById('gitInfoModal');

    if (fetchAllBtn) fetchAllBtn.addEventListener('click', () => startGitFetch('all'));
    if (refreshReposBtn) refreshReposBtn.addEventListener('click', () => loadGitRepos(false, true));
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadGitRepos());
    if (batchFetchBtn) batchFetchBtn.addEventListener('click', () => {
        document.querySelectorAll('.git-repo input[data-action="batch-select"]:checked').forEach((cb) => {
            const row = cb.closest('.git-repo');
            const btn = row ? row.querySelector('button[data-action="fetch-one"]') : null;
            if (btn) btn.click();
        });
    });
    if (batchUpdateBtn) batchUpdateBtn.addEventListener('click', () => runBatchAction('update'));
    if (batchPushBtn) batchPushBtn.addEventListener('click', () => runBatchAction('push'));
    if (gitInfoModalClose) gitInfoModalClose.addEventListener('click', hideGitInfoModal);
    if (gitInfoModalCopy) gitInfoModalCopy.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(_gitLastModalText || ''); setGitStatus('Modal text copied.', 'success'); } catch (_) {}
    });
    if (gitInfoModal) gitInfoModal.addEventListener('click', (e) => { if (e.target === gitInfoModal) hideGitInfoModal(); });
    
    const gitCommitsModalClose = document.getElementById('gitCommitsModalClose');
    const gitCommitsModal = document.getElementById('gitCommitsModal');
    if (gitCommitsModalClose) gitCommitsModalClose.addEventListener('click', closeGitCommitsModal);
    if (gitCommitsModal) gitCommitsModal.addEventListener('click', (e) => { if (e.target === gitCommitsModal) closeGitCommitsModal(); });

    const gitCommitsSearchInput = document.getElementById('gitCommitsSearchInput');
    if (gitCommitsSearchInput) gitCommitsSearchInput.addEventListener('input', (e) => _filterGitCommits(e.target.value));

    const gitCommitsList = document.getElementById('gitCommitsList');
    if (gitCommitsList) gitCommitsList.addEventListener('click', async (e) => {
        const copyBtn = e.target.closest('[data-action="copy-commit-sha"]');
        if (!copyBtn) return;
        const sha = copyBtn.getAttribute('data-sha') || '';
        const ok = await copyTextToClipboard(sha);
        if (typeof showGitflowToast === 'function') {
            ok ? showGitflowToast('Copied', `Commit hash ${sha.slice(0, 10)} copied to clipboard.`)
               : showGitflowToast('Copy failed', 'Could not access the clipboard. Select the hash text manually instead.', 'error');
        }
    });
    const onFilterChange = () => {
        _gitFilters.dirty = !!(fDirty && fDirty.checked);
        _gitFilters.behind = !!(fBehind && fBehind.checked);
        _gitFilters.ahead = !!(fAhead && fAhead.checked);
        _gitFilters.conflict = !!(fConflict && fConflict.checked);
        loadGitRepos(true);
    };
    if (fDirty) fDirty.addEventListener('change', onFilterChange);
    if (fBehind) fBehind.addEventListener('change', onFilterChange);
    if (fAhead) fAhead.addEventListener('change', onFilterChange);
    if (fConflict) fConflict.addEventListener('change', onFilterChange);

    // Wire Screen 2 navigation controls
    _initScreen2Controls();

    const onRepoListClick = (e) => {
            const fetchBtn = e.target && e.target.closest ? e.target.closest('button[data-action="fetch-one"]') : null;
            const updateBtn = e.target && e.target.closest ? e.target.closest('button[data-action="update-one"]') : null;
            const pushBtn = e.target && e.target.closest ? e.target.closest('button[data-action="push-one"]') : null;
            const favBtn = e.target && e.target.closest ? e.target.closest('button[data-action="toggle-favorite"]') : null;
            const copyFetchBtn = e.target && e.target.closest ? e.target.closest('button[data-action="copy-cmd-fetch"]') : null;
            const copyPullBtn = e.target && e.target.closest ? e.target.closest('button[data-action="copy-cmd-pull"]') : null;
            const copyPushBtn = e.target && e.target.closest ? e.target.closest('button[data-action="copy-cmd-push"]') : null;
            const previewBtn = e.target && e.target.closest ? e.target.closest('button[data-action="sync-preview"]') : null;
            const stashPullPopBtn = e.target && e.target.closest ? e.target.closest('button[data-action="stash-pull-pop"]') : null;
            const resolveDivergedBtn = e.target && e.target.closest ? e.target.closest('button[data-action="resolve-diverged-rebase"]') : null;
            const resolveDivergedMergeBtn = e.target && e.target.closest ? e.target.closest('button[data-action="resolve-diverged-merge"]') : null;
            const aiBtn = e.target && e.target.closest ? e.target.closest('button[data-action="ai-commit"]') : null;
            const aiOpen = e.target && e.target.closest ? e.target.closest('[data-action="ai-open"]') : null;
            
            if (fetchBtn) {
                const row = fetchBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                startGitFetch('one', repoPath, fetchBtn);
            } else if (favBtn) {
                const row = favBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (_gitFavorites.has(repoPath)) _gitFavorites.delete(repoPath); else _gitFavorites.add(repoPath);
                _saveGitState();
                loadGitRepos(true);
            } else if (copyFetchBtn || copyPullBtn || copyPushBtn) {
                const row = (copyFetchBtn || copyPullBtn || copyPushBtn).closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                const cmd = copyFetchBtn ? `git -C "${repoPath}" fetch --all --prune` : copyPullBtn ? `git -C "${repoPath}" pull` : `git -C "${repoPath}" push`;
                navigator.clipboard.writeText(cmd).then(() => setGitStatus('Command copied.', 'success')).catch(() => {});
            } else if (previewBtn) {
                const row = previewBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                const branchSel = row.querySelector('select[data-action="branch-select"]');
                const branch = String((branchSel && branchSel.value) || '');
                const repoNow = (Array.isArray(_gitLastRenderedRepos) ? _gitLastRenderedRepos : []).find((x) => String(x.path || '') === String(repoPath));
                const behind = Number((repoNow && repoNow.behind) || 0);
                const ahead = Number((repoNow && repoNow.ahead) || 0);
                const dirty = !!(repoNow && repoNow.dirty);
                const plan = [
                    `Sync plan for ${PathBasename(repoPath)} (${branch || 'current'})`,
                    `1. git fetch --all --prune`,
                    `2. Check ahead/behind`,
                    behind > 0 ? `3. pull/update (${behind} behind)` : '3. pull/update (skip: not behind)',
                    ahead > 0 ? `4. push (${ahead} ahead)` : '4. push (skip: not ahead)',
                    dirty ? '5. working tree dirty: commit or stash first' : '5. working tree clean',
                ];
                showGitInfoModal(`Sync plan: ${PathBasename(repoPath)}`, plan.join('\n'));
            } else if (stashPullPopBtn) {
                const row = stashPullPopBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                runGitStashPullPop(repoPath, stashPullPopBtn);
            } else if (resolveDivergedBtn) {
                const row = resolveDivergedBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                const branchSel = row.querySelector('select[data-action="branch-select"]');
                const branch = String((branchSel && branchSel.value) || '').trim() || 'main';
                const guide = [
                    `Resolve Diverged (Rebase) for ${PathBasename(repoPath)}:${branch}`,
                    '',
                    '1) Ensure working tree is clean (commit/stash first):',
                    `git -C "${repoPath}" status`,
                    '',
                    '2) Fetch latest remote refs:',
                    `git -C "${repoPath}" fetch --all --prune`,
                    '',
                    '3) Checkout target branch:',
                    `git -C "${repoPath}" checkout ${branch}`,
                    '',
                    '4) Rebase onto remote tracking branch:',
                    `git -C "${repoPath}" pull --rebase origin ${branch}`,
                    '',
                    '5) If conflicts happen:',
                    '# resolve files manually, then:',
                    `git -C "${repoPath}" add -A`,
                    `git -C "${repoPath}" rebase --continue`,
                    '# abort if needed:',
                    `git -C "${repoPath}" rebase --abort`,
                    '',
                    '6) Push updated history safely:',
                    `git -C "${repoPath}" push --force-with-lease`,
                    '',
                    '7) Refresh Git panel.',
                ].join('\n');
                showGitInfoModal(`Resolve Diverged: ${PathBasename(repoPath)}`, guide);
            } else if (resolveDivergedMergeBtn) {
                const row = resolveDivergedMergeBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                const branchSel = row.querySelector('select[data-action="branch-select"]');
                const branch = String((branchSel && branchSel.value) || '').trim() || 'main';
                const guide = [
                    `Resolve Diverged (Merge) for ${PathBasename(repoPath)}:${branch}`,
                    '',
                    '1) Ensure working tree is clean (commit/stash first):',
                    `git -C "${repoPath}" status`,
                    '',
                    '2) Fetch latest remote refs:',
                    `git -C "${repoPath}" fetch --all --prune`,
                    '',
                    '3) Checkout target branch:',
                    `git -C "${repoPath}" checkout ${branch}`,
                    '',
                    '4) Merge remote tracking branch into local:',
                    `git -C "${repoPath}" merge origin/${branch}`,
                    '',
                    '5) If conflicts happen:',
                    '# resolve files manually, then:',
                    `git -C "${repoPath}" add -A`,
                    `git -C "${repoPath}" commit`,
                    '# abort if needed:',
                    `git -C "${repoPath}" merge --abort`,
                    '',
                    '6) Push normally:',
                    `git -C "${repoPath}" push`,
                    '',
                    '7) Refresh Git panel.',
                ].join('\n');
                showGitInfoModal(`Resolve Diverged (Merge): ${PathBasename(repoPath)}`, guide);
            } else if (e.target && e.target.closest('button[data-action="checkout-branch-btn"]')) {
                const checkoutBtn = e.target.closest('button[data-action="checkout-branch-btn"]');
                const row = checkoutBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                const branchSel = row.querySelector('select[data-action="branch-select"]');
                const branch = String((branchSel && branchSel.value) || '').trim();
                if (!branch) return;
                runGitBranchAction(repoPath, branch, 'checkout', checkoutBtn);
            } else if (updateBtn) {
                const row = updateBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                runGitPull(repoPath, updateBtn);
            } else if (pushBtn) {
                const row = pushBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                runGitPush(repoPath, pushBtn);
            } else if (aiBtn) {
                const row = aiBtn.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                const sel = row.querySelector && row.querySelector('select[data-action="branch-select"]');
                const branch = sel && sel.value ? String(sel.value) : '';
                openAiCommitModal(repoPath, branch);
            } else if (aiOpen) {
                const row = aiOpen.closest('.git-repo');
                if (!row) return;
                const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                if (!repoPath) return;
                const sel = row.querySelector && row.querySelector('select[data-action="branch-select"]');
                const branch = sel && sel.value ? String(sel.value) : '';
                if (!branch) return;
                const state = _getAiState(repoPath, branch);
                openAiCommitModal(repoPath, branch, { prefillMessage: state && state.message ? String(state.message) : '', mode: (state && state.status) ? String(state.status) : '' });
            } else {
                const actionPullBtn = e.target && e.target.closest ? e.target.closest('button[data-action="branch-action-pull"]') : null;
                const actionMergeThisBtn = e.target && e.target.closest ? e.target.closest('button[data-action="branch-action-merge-this"]') : null;
                const actionSyncAllBtn = e.target && e.target.closest ? e.target.closest('button[data-action="branch-action-sync-all"]') : null;
                
                if (actionPullBtn) {
                    const row = actionPullBtn.closest('.git-repo');
                    if (!row) return;
                    const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                    if (!repoPath) return;
                    const branch = actionPullBtn.getAttribute('data-branch') || '';
                    runGitBranchAction(repoPath, branch, 'pull', actionPullBtn);
                } else if (actionSyncAllBtn) {
                    const row = actionSyncAllBtn.closest('.git-repo');
                    if (!row) return;
                    const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                    if (!repoPath) return;
                    runGitSyncAll(repoPath, actionSyncAllBtn);
                } else if (actionMergeThisBtn) {
                    const row = actionMergeThisBtn.closest('.git-repo');
                    if (!row) return;
                    const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
                    if (!repoPath) return;
                    const branch = actionMergeThisBtn.getAttribute('data-branch') || '';
                    runGitBranchAction(repoPath, branch, 'merge-this-into-current', actionMergeThisBtn);
                }
            }
    };
    if (repoListApps) repoListApps.addEventListener('click', onRepoListClick);
    if (repoListPackages) repoListPackages.addEventListener('click', onRepoListClick);

    const onRepoListChange = async (e) => {
        const sel = e.target && e.target.closest ? e.target.closest('select[data-action="branch-select"]') : null;
        if (!sel) return;
        const row = sel.closest('.git-repo');
        if (!row) return;
        const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
        if (!repoPath) return;
        const branch = String(sel.value || '').trim();
        if (!branch) return;
        if (branch.startsWith('origin/') || branch.includes('/')) {
            // Remote branches are shown for visibility, but status is computed for local branches.
            setGitStatus('Select a local branch (create a tracking branch for remote ones).', 'error');
            return;
        }
        _gitBranchChoices.set(repoPath, branch);
        // Keep the selected value clean (no ↓/↑ suffixes). Options may include suffixes for scanning.
        try {
            const opt = sel.querySelector(`option[value="${CSS.escape(branch)}"]`);
            if (opt) opt.textContent = branch;
        } catch (_) {}
        try {
            setGitStatus(`Checking ${PathBasename(repoPath)}:${branch}…`);
        } catch (_) {}
        try {
            const status = await loadRepoStatus(repoPath, branch);
            // Refresh list to reflect new selection & badges (keep this lightweight).
            // We reload all repos to avoid partial DOM diffing.
            loadGitRepos();
            setGitStatus('Ready.');
        } catch (err) {
            setGitStatus(`Branch status failed: ${err.message}`, 'error');
        }
    };
    if (repoListApps) repoListApps.addEventListener('change', onRepoListChange);
    if (repoListPackages) repoListPackages.addEventListener('change', onRepoListChange);

    const onRepoListPointerDown = async (e) => {
        const sel = e.target && e.target.closest ? e.target.closest('select[data-action="branch-select"]') : null;
        if (!sel) return;
        // Populate the dropdown on first open.
        if (sel.dataset.loaded === '1' || sel.dataset.loaded === 'pending') return;
        const row = sel.closest('.git-repo');
        const repoPath = row ? decodeURIComponent(row.getAttribute('data-repo-path-enc') || '') : '';
        if (!repoPath) return;
        sel.dataset.loaded = 'pending';
        sel.innerHTML = `<option value="">Loading…</option>`;
        try {
            const data = await loadRepoBranches(repoPath);
            _gitBranchStatusCache.set(repoPath, data);
            populateSelectWithOptions(sel, repoPath, data);
        } catch (err) {
            sel.dataset.loaded = '0';
            sel.innerHTML = `<option value="">Failed</option>`;
        }
    };
    if (repoListApps) repoListApps.addEventListener('pointerdown', onRepoListPointerDown);
    if (repoListPackages) repoListPackages.addEventListener('pointerdown', onRepoListPointerDown);

    // Click on behind/ahead badges to show branches list (popover)
    const popover = document.getElementById('gitBranchPopover');
    const popoverTitle = document.getElementById('gitBranchPopoverTitle');
    const popoverList = document.getElementById('gitBranchPopoverList');

    const hidePopover = () => {
        if (!popover) return;
        popover.classList.add('hidden');
    };

    const positionPopover = (clientX, clientY) => {
        if (!popover) return;
        const padding = 12;
        const width = Math.min(520, window.innerWidth - padding * 2);
        popover.style.width = `${width}px`;
        // Measure after width applied
        const rect = popover.getBoundingClientRect();
        const left = Math.min(Math.max(padding, clientX - width / 2), window.innerWidth - width - padding);
        const top = Math.min(Math.max(padding, clientY + 12), window.innerHeight - rect.height - padding);
        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;
    };

    const showBranchPopover = async ({ repoPath, mode, clientX, clientY }) => {
        if (!popover || !popoverTitle || !popoverList) return;
        popoverTitle.textContent = mode === 'behind' ? 'Branches behind (need pull)' : 'Branches ahead (need push)';
        popoverList.innerHTML = '<div style="color:#aaa;">Loading…</div>';
        popover.classList.remove('hidden');
        positionPopover(clientX, clientY);

        let data = _gitBranchStatusCache.get(repoPath);
        if (!data) {
            try {
                data = await loadRepoBranches(repoPath);
                _gitBranchStatusCache.set(repoPath, data);
            } catch (err) {
                popoverList.innerHTML = `<div style="color:#ff8a8a;">Failed: ${escapeHtml(err.message)}</div>`;
                return;
            }
        }

        const branchStatuses = Array.isArray(data.branchStatuses) ? data.branchStatuses : [];
        const items = branchStatuses
            .map((s) => ({
                name: String(s.name || ''),
                behind: (s.behind === null || s.behind === undefined) ? 0 : Number(s.behind),
                ahead: (s.ahead === null || s.ahead === undefined) ? 0 : Number(s.ahead),
                hasUpstream: s.hasUpstream !== false,
            }))
            .filter((s) => s.name);

        const filtered = items
            .filter((s) => mode === 'behind' ? (s.behind > 0) : (s.ahead > 0))
            .sort((a, b) => {
                const primary = mode === 'behind' ? (b.behind - a.behind) : (b.ahead - a.ahead);
                if (primary !== 0) return primary;
                return a.name.localeCompare(b.name);
            });

        if (filtered.length === 0) {
            popoverList.innerHTML = '<div style="color:#aaa;">No branches.</div>';
            return;
        }

        popoverList.innerHTML = filtered.map((b) => {
            const badges = [];
            if (!b.hasUpstream) badges.push(`<span class="git-badge noupstream">no upstream</span>`);
            if (b.behind > 0) badges.push(`<span class="git-badge behind">↓ ${b.behind}</span>`);
            if (b.ahead > 0) badges.push(`<span class="git-badge ahead">↑ ${b.ahead}</span>`);
            return `<div class="git-branch-row"><div class="name">${escapeHtml(b.name)}</div><div class="badges">${badges.join('')}</div></div>`;
        }).join('');
    };

    const onRepoBadgeClick = (e) => {
        const badge = e.target && e.target.closest ? e.target.closest('.git-badge.clickable') : null;
        if (!badge) return;
        // Only handle ahead/behind badges here. (AI badges are handled separately.)
        const action = badge.getAttribute('data-action') || '';
        if (action !== 'show-ahead' && action !== 'show-behind') return;
        const row = badge.closest('.git-repo');
        if (!row) return;
        const repoPath = decodeURIComponent(row.getAttribute('data-repo-path-enc') || '');
        if (!repoPath) return;
        const mode = action === 'show-ahead' ? 'ahead' : 'behind';
        e.preventDefault();
        e.stopPropagation();
        showBranchPopover({ repoPath, mode, clientX: e.clientX, clientY: e.clientY });
    };

    if (repoListApps) repoListApps.addEventListener('click', onRepoBadgeClick, true);
    if (repoListPackages) repoListPackages.addEventListener('click', onRepoBadgeClick, true);

    document.addEventListener('click', (e) => {
        if (!popover || popover.classList.contains('hidden')) return;
        const inside = e.target && e.target.closest ? e.target.closest('#gitBranchPopover') : null;
        if (inside) return;
        hidePopover();
    }, true);

    async function loadWorkspaceInfo() {
        try {
            const res = await fetch(apiUrl('/api/workspace'));
            const data = await res.json();
            if (data.success && data.workspace) {
                const el = document.getElementById('currentWorkspacePath');
                if (el) {
                    el.textContent = data.workspace;
                    el.title = data.workspace;
                }
            }
        } catch (e) {
            console.warn('Failed to load workspace info', e);
        }
    }

    function _initWorkspaceSwitcher() {
        const modal = document.getElementById('gitSwitchWorkspaceModal');
        const btn = document.getElementById('gitSwitchWorkspaceBtn');
        const input = document.getElementById('gitSwitchWorkspaceInput');
        const submit = document.getElementById('gitSwitchWorkspaceSubmit');
        const cancel = document.getElementById('gitSwitchWorkspaceCancel');
        const close = document.getElementById('gitSwitchWorkspaceClose');
        const pathEl = document.getElementById('currentWorkspacePath');

        if (!modal || !btn) return;

        const openModal = () => {
            if (input && pathEl) {
                input.value = (pathEl.textContent === 'Loading...' ? '' : pathEl.textContent);
            }
            modal.classList.remove('hidden');
            if (input) input.focus();
        };

        const closeModal = () => {
            modal.classList.add('hidden');
        };

        btn.addEventListener('click', openModal);
        if (cancel) cancel.addEventListener('click', closeModal);
        if (close) close.addEventListener('click', closeModal);

        if (submit) {
            submit.addEventListener('click', async () => {
                const newPath = (input ? input.value : '').trim();
                if (!newPath) return;
                submit.disabled = true;
                submit.textContent = 'Switching...';
                try {
                    const res = await fetch(apiUrl('/api/workspace/switch'), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ workspace: newPath })
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(`Switched workspace to ${data.name || data.workspace}`, 'success');
                        if (pathEl) {
                            pathEl.textContent = data.workspace;
                            pathEl.title = data.workspace;
                        }
                        closeModal();
                        loadGitRepos(true);
                    } else {
                        showToast(data.error || 'Failed to switch workspace', 'error');
                    }
                } catch (err) {
                    showToast(err.message, 'error');
                } finally {
                    submit.disabled = false;
                    submit.textContent = 'Switch Workspace';
                }
            });
        }
    }

    // Render shimmers immediately on initial load
    renderGitShimmers();
    setTimeout(() => {
        loadWorkspaceInfo();
        _initWorkspaceSwitcher();
        loadGitRepos();
        startGitFetch('all');
        requestNotificationPermission();
    }, 100);

    // Call git fetch status every 30 minutes
    setInterval(() => {
        startGitFetch('all');
    }, 30 * 60 * 1000);
})();

// --- AI Commit UI ---
let _aiCommitRepoPath = '';
let _aiCommitIsWorking = false;
let _aiPollingJobs = new Set();
let _aiCommitBranch = '';

function setAiCommitStatus(text, kind = null) {
    const el = getEl('aiCommitStatus');
    if (!el) return;
    el.textContent = String(text || '');
    el.style.color = kind === 'error' ? '#ff8a8a' : kind === 'success' ? '#8fe0a1' : '#aaa';
}

function setAiCommitWorking(isWorking) {
    _aiCommitIsWorking = !!isWorking;
    const genBtn = getEl('aiCommitGenerateBtn');
    const regenBtn = getEl('aiCommitRegenerateBtn');
    const genCommitBtn = getEl('aiCommitGenCommitBtn');
    const genCommitPushBtn = getEl('aiCommitGenCommitPushBtn');
    if (genBtn) genBtn.disabled = _aiCommitIsWorking;
    if (regenBtn) regenBtn.disabled = _aiCommitIsWorking;
    if (genCommitBtn) genCommitBtn.disabled = _aiCommitIsWorking;
    if (genCommitPushBtn) genCommitPushBtn.disabled = _aiCommitIsWorking;
}

async function aiGenerateThenCommit({ push }) {
    if (_aiCommitIsWorking) return;
    const repoPath = String(_aiCommitRepoPath || '');
    if (!repoPath) return;

    const stagedEl = getEl('aiCommitUseStaged');
    const unstagedEl = getEl('aiCommitUseUnstaged');
    const stageAllEl = getEl('aiCommitStageAll');
    const msgEl = getEl('aiCommitMessage');

    const branch = String(_aiCommitBranch || _gitBranchChoices.get(repoPath) || '');

    const staged = !!(stagedEl && stagedEl.checked);
    const unstaged = !!(unstagedEl && unstagedEl.checked);
    const stageAll = !!(stageAllEl && stageAllEl.checked);

    if (!staged && !unstaged) {
        setAiCommitStatus('Select staged and/or unstaged diff.', 'error');
        return;
    }

    const modal = getEl('aiCommitModal');
    const selectedFiles = [];
    if (modal) {
        modal.querySelectorAll('.ai-commit-file-chk:checked').forEach(chk => {
            selectedFiles.push(chk.value);
        });
    }

    setAiCommitWorking(true);
    setAiCommitStatus(push ? 'Generating message, then commit & push…' : 'Generating message, then commit…');

    try {
        // Show loader/badge in the repo card while this runs.
        if (branch) {
            _setAiState(repoPath, branch, { status: 'generating', jobId: '', message: '', committed: false });
            loadGitRepos(true);
        }

        // 1) Start generation job
        const genRes = await fetch(apiUrl('/api/git/ai/commit-message'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, staged, unstaged, selectedFiles }),
        });
        const genData = await genRes.json();
        if (!genData.success || !genData.jobId) throw new Error(genData.error || 'Failed to start AI generation');

        // 2) Poll generation job
        const genJobId = String(genData.jobId);
        if (branch) {
            _setAiState(repoPath, branch, { status: 'generating', jobId: genJobId, message: '', committed: false });
            loadGitRepos(true);
        }
        let message = '';
        while (true) {
            const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(genJobId)}`));
            const data = await res.json();
            if (!data.success || !data.job) throw new Error(data.error || 'Failed to read AI job');
            const job = data.job;
            if (job.status === 'running' || job.status === 'stopping') {
                setAiCommitStatus('Generating commit message…');
                await new Promise((r) => setTimeout(r, 900));
                continue;
            }
            if (job.status === 'success' && job.result && job.result.message) {
                message = String(job.result.message).trim();
                break;
            }
            const errText = String(job.error || job.output || 'AI generation failed').trim();
            throw new Error(errText);
        }

        if (!message) throw new Error('AI returned empty commit message');
        if (msgEl) msgEl.value = message;
        if (branch) {
            _setAiState(repoPath, branch, { status: 'ready', jobId: '', message, committed: false });
            loadGitRepos(true);
        }

        // 3) Start commit (optionally push)
        setAiCommitStatus(push ? 'Committing & pushing…' : 'Committing…');
        if (branch) {
            const prev = _getAiState(repoPath, branch) || {};
            _setAiState(repoPath, branch, { ...prev, status: 'committing' });
            loadGitRepos(true);
        }
        const commitRes = await fetch(apiUrl('/api/git/commit'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, message, push: !!push, stageAll, selectedFiles }),
        });
        const commitData = await commitRes.json();
        if (!commitData.success || !commitData.jobId) throw new Error(commitData.error || 'Commit failed to start');

        await pollAiCommitJob(String(commitData.jobId));
        // pollAiCommitJob closes modal + refreshes repos on success and clears AI cache.
    } catch (e) {
        if (branch) {
            _setAiState(repoPath, branch, { status: 'error', error: String(e && e.message ? e.message : e), jobId: '' });
            loadGitRepos(true);
        }
        setAiCommitStatus(String(e && e.message ? e.message : e), 'error');
        showToast('Generate+commit failed', 'error');
    } finally {
        setAiCommitWorking(false);
    }
}

async function openAiCommitModal(repoPath, branch = '', options = null) {
    const modal = getEl('aiCommitModal');
    const meta = getEl('aiCommitRepoMeta');
    const msg = getEl('aiCommitMessage');
    const modelHint = getEl('aiCommitModelHint');
    const stagedEl = getEl('aiCommitUseStaged');
    const unstagedEl = getEl('aiCommitUseUnstaged');
    const fileListContainer = getEl('aiCommitFileListContainer');
    const fileList = getEl('aiCommitFileList');

    if (!modal || !meta || !msg) return;
    _aiCommitRepoPath = String(repoPath || '');
    _aiCommitBranch = String(branch || '');
    meta.textContent = _aiCommitRepoPath;
    msg.value = '';
    if (modelHint) modelHint.textContent = '';
    setAiCommitStatus('Ready.');

    modal.classList.remove('hidden');
    modal.style.display = 'flex';

    if (fileListContainer) fileListContainer.style.display = 'none';
    if (fileList) fileList.innerHTML = '';

    // If opened from "Commit message ready", prefill the message and show a clear hint.
    const prefill = options && options.prefillMessage ? String(options.prefillMessage) : '';
    const mode = options && options.mode ? String(options.mode) : '';
    if (prefill.trim()) {
        msg.value = prefill.trim();
        setAiCommitStatus('Commit message loaded. Choose Commit or Commit & Push.', 'success');
    } else if (mode === 'error') {
        setAiCommitStatus('AI generation failed earlier. You can regenerate a new message.', 'error');
    }

    // Auto-select diff scope to prevent the common "nothing staged" error:
    // If the repo is dirty but has only unstaged changes, enable "Include unstaged diff".
    try {
        if (stagedEl) stagedEl.checked = true;
        if (unstagedEl) unstagedEl.checked = false;
        const res = await fetch(apiUrl(`/api/git/changes?repoPath=${encodeURIComponent(_aiCommitRepoPath)}`));
        const data = await res.json();
        if (data && data.success && data.changes) {
            const hasStaged = !!data.changes.hasStaged;
            const hasUnstaged = !!data.changes.hasUnstaged;
            const dirty = !!data.changes.dirty;
            if (dirty && !hasStaged && hasUnstaged) {
                if (unstagedEl) unstagedEl.checked = true;
                setAiCommitStatus('Tip: nothing is staged; using unstaged diff.', 'success');
            }
            if (!dirty && !hasStaged && !hasUnstaged) {
                setAiCommitStatus('Working tree is clean for this repo.', 'error');
            }

            // Render file list if changes.files exists
            if (Array.isArray(data.changes.files) && data.changes.files.length > 0 && fileList && fileListContainer) {
                fileListContainer.style.display = 'block';
                fileList.innerHTML = data.changes.files.map(file => {
                    const statusText = file.staged ? 'Staged' : file.untracked ? 'Untracked' : 'Unstaged';
                    const color = file.staged ? '#48bb78' : file.untracked ? '#cbd5e1' : '#e53e3e';
                    return `
                        <label style="display:flex; align-items:center; gap:8px; font-size:12px; color:#cbd5e1; cursor:pointer; padding:2px 0;">
                            <input type="checkbox" class="ai-commit-file-chk" value="${escapeHtml(file.path)}" checked />
                            <span style="font-family:'JetBrains Mono',monospace; word-break:break-all;">${escapeHtml(file.path)}</span>
                            <span style="font-size:10px; color:${color}; margin-left:auto; font-weight:600;">[${statusText}]</span>
                        </label>
                    `;
                }).join('');

                // Wire up Select All / Deselect All button clicks
                const selectAllBtn = getEl('aiCommitSelectAllBtn');
                const deselectAllBtn = getEl('aiCommitDeselectAllBtn');
                if (selectAllBtn) {
                    selectAllBtn.onclick = () => {
                        modal.querySelectorAll('.ai-commit-file-chk').forEach(chk => chk.checked = true);
                    };
                }
                if (deselectAllBtn) {
                    deselectAllBtn.onclick = () => {
                        modal.querySelectorAll('.ai-commit-file-chk').forEach(chk => chk.checked = false);
                    };
                }
            }
        }
    } catch (e) {
        console.error("Failed to load changes for selective commit", e);
    }
}

function closeAiCommitModal() {
    const modal = getEl('aiCommitModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.style.display = 'none';
    _aiCommitRepoPath = '';
    setAiCommitWorking(false);
}

async function generateAiCommitMessage(isRegenerate = false) {
    if (_aiCommitIsWorking) return;
    const repoPath = String(_aiCommitRepoPath || '');
    if (!repoPath) return;

    const stagedEl = getEl('aiCommitUseStaged');
    const unstagedEl = getEl('aiCommitUseUnstaged');
    const msgEl = getEl('aiCommitMessage');
    const modelHint = getEl('aiCommitModelHint');

    const staged = !!(stagedEl && stagedEl.checked);
    const unstaged = !!(unstagedEl && unstagedEl.checked);
    if (!staged && !unstaged) {
        setAiCommitStatus('Select staged and/or unstaged diff.', 'error');
        return;
    }

    const modal = getEl('aiCommitModal');
    const selectedFiles = [];
    if (modal) {
        modal.querySelectorAll('.ai-commit-file-chk:checked').forEach(chk => {
            selectedFiles.push(chk.value);
        });
    }

    setAiCommitWorking(true);
    setAiCommitStatus(isRegenerate ? 'Regenerating…' : 'Generating…');

    try {
        const res = await fetch(apiUrl('/api/git/ai/commit-message'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, staged, unstaged, selectedFiles }),
        });
        const data = await res.json();
        if (!data.success) {
            const details = data && data.details ? data.details : null;
            if (details && details.hint) {
                throw new Error(`${data.error || 'AI generation failed'} (${details.hint})`);
            }
            throw new Error(data.error || 'AI generation failed');
        }
        if (!data.jobId) throw new Error('AI generation started but no jobId returned');
        const branch = String(_aiCommitBranch || _gitBranchChoices.get(repoPath) || '');
        _setAiState(repoPath, branch, { status: 'generating', jobId: String(data.jobId), message: '', committed: false });
        loadGitRepos(true);
        closeAiCommitModal();
        showToast('Generating commit message in background…', 'success');
        pollAiMessageJob(repoPath, branch, String(data.jobId));
    } catch (e) {
        setAiCommitStatus(String(e && e.message ? e.message : e), 'error');
    } finally {
        setAiCommitWorking(false);
    }
}

async function pollAiMessageJob(repoPath, branch, jobId) {
    const key = `${repoPath}::${branch}::${jobId}`;
    if (_aiPollingJobs.has(key)) return;
    _aiPollingJobs.add(key);
    try {
        while (true) {
            const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`));
            const data = await res.json();
            if (!data.success || !data.job) throw new Error(data.error || 'Failed to read job status');
            const job = data.job;
            if (job.status === 'running' || job.status === 'stopping') {
                await new Promise((r) => setTimeout(r, 900));
                continue;
            }
            if (job.status === 'success' && job.result && job.result.message) {
                _setAiState(repoPath, branch, { status: 'ready', jobId: '', message: String(job.result.message).trim(), committed: false });
                loadGitRepos(true);
                showToast('Commit message ready', 'success');
                return;
            }
            const errText = (job.error || job.output || 'AI generation failed');
            _setAiState(repoPath, branch, { status: 'error', error: String(errText).trim(), jobId: '' });
            loadGitRepos(true);
            showToast('AI generation failed', 'error');
            return;
        }
    } catch (e) {
        _setAiState(repoPath, branch, { status: 'error', error: String(e && e.message ? e.message : e), jobId: '' });
        loadGitRepos(true);
    } finally {
        _aiPollingJobs.delete(key);
    }
}

async function pollAiCommitJob(jobId) {
    const cancelBtn = document.getElementById('aiCommitCancelBtn');
    const genBtn = document.getElementById('aiCommitGenerateBtn');
    const regenBtn = document.getElementById('aiCommitRegenerateBtn');
    const genCommitBtn = document.getElementById('aiCommitGenCommitBtn');
    const genCommitPushBtn = document.getElementById('aiCommitGenCommitPushBtn');
    if (cancelBtn) cancelBtn.disabled = true;
    if (genBtn) genBtn.disabled = true;
    if (regenBtn) regenBtn.disabled = true;
    if (genCommitBtn) genCommitBtn.disabled = true;
    if (genCommitPushBtn) genCommitPushBtn.disabled = true;

    try {
        while (true) {
            const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`));
            const data = await res.json();
            if (!data.success || !data.job) throw new Error(data.error || 'Failed to read job status');
            const job = data.job;
            if (job.status === 'running' || job.status === 'stopping') {
                setAiCommitStatus('Commit job running in background…');
                await new Promise((r) => setTimeout(r, 900));
                continue;
            }
            if (job.status === 'success') {
                setAiCommitStatus('Commit completed.', 'success');
                showToast('Commit complete', 'success');
                try {
                    const repoPath = String(_aiCommitRepoPath || '');
                    const branch = String(_aiCommitBranch || _gitBranchChoices.get(repoPath) || '');
                    if (repoPath && branch) _clearAiState(repoPath, branch);
                } catch (_) {}
                closeAiCommitModal();
                loadGitRepos(true);
                return;
            }
            const errText = (job.error || job.output || 'Commit failed');
            throw new Error(String(errText).trim());
        }
    } finally {
        if (cancelBtn) cancelBtn.disabled = false;
        if (genBtn) genBtn.disabled = false;
        if (regenBtn) regenBtn.disabled = false;
        if (genCommitBtn) genCommitBtn.disabled = false;
        if (genCommitPushBtn) genCommitPushBtn.disabled = false;
    }
}

async function startAiCommitJob(repoPath, branch, message, push) {
    const safeRepoPath = String(repoPath || '');
    const safeBranch = String(branch || '');
    _setAiState(safeRepoPath, safeBranch, { ...(_getAiState(safeRepoPath, safeBranch) || {}), status: 'committing' });
    loadGitRepos(true);

    try {
        const res = await fetch(apiUrl('/api/git/commit'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath: safeRepoPath, message, push, stageAll: true }),
        });
        const data = await res.json();
        if (!data.success || !data.jobId) throw new Error(data.error || 'Commit failed to start');
        pollAiCommitJobForRow(safeRepoPath, safeBranch, String(data.jobId), push);
    } catch (e) {
        _setAiState(safeRepoPath, safeBranch, { status: 'error', error: String(e && e.message ? e.message : e) });
        loadGitRepos(true);
        showToast('Commit failed to start', 'error');
    }
}

async function pollAiCommitJobForRow(repoPath, branch, jobId, didPush) {
    const key = `commit::${repoPath}::${branch}::${jobId}`;
    if (_aiPollingJobs.has(key)) return;
    _aiPollingJobs.add(key);
    try {
        while (true) {
            const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(jobId)}`));
            const data = await res.json();
            if (!data.success || !data.job) throw new Error(data.error || 'Failed to read job status');
            const job = data.job;
            if (job.status === 'running' || job.status === 'stopping') {
                _setAiState(repoPath, branch, { ...(_getAiState(repoPath, branch) || {}), status: 'committing' });
                loadGitRepos(true);
                await new Promise((r) => setTimeout(r, 900));
                continue;
            }
            if (job.status === 'success') {
                // Commit message was consumed; clear the persisted "ready" state so it doesn't linger after success.
                _clearAiState(repoPath, branch);
                loadGitRepos(true);
                showToast(didPush ? 'Commit & push complete' : 'Commit complete', 'success');
                return;
            }
            const errText = (job.error || job.output || 'Commit failed');
            throw new Error(String(errText).trim());
        }
    } catch (e) {
        const prev = _getAiState(repoPath, branch) || {};
        _setAiState(repoPath, branch, { ...prev, status: 'error', error: String(e && e.message ? e.message : e) });
        loadGitRepos(true);
        showToast('Commit failed', 'error');
    } finally {
        _aiPollingJobs.delete(key);
    }
}

(() => {
    const modal = document.getElementById('aiCommitModal');
    const closeBtn = document.getElementById('aiCommitCloseBtn');
    const cancelBtn = document.getElementById('aiCommitCancelBtn');
    const genBtn = document.getElementById('aiCommitGenerateBtn');
    const regenBtn = document.getElementById('aiCommitRegenerateBtn');
    const genCommitBtn = document.getElementById('aiCommitGenCommitBtn');
    const genCommitPushBtn = document.getElementById('aiCommitGenCommitPushBtn');

    if (closeBtn) closeBtn.addEventListener('click', () => closeAiCommitModal());
    if (cancelBtn) cancelBtn.addEventListener('click', () => closeAiCommitModal());
    if (genBtn) genBtn.addEventListener('click', () => generateAiCommitMessage(false));
    if (regenBtn) regenBtn.addEventListener('click', () => generateAiCommitMessage(true));
    if (genCommitBtn) genCommitBtn.addEventListener('click', () => aiGenerateThenCommit({ push: false }));
    if (genCommitPushBtn) genCommitPushBtn.addEventListener('click', () => aiGenerateThenCommit({ push: true }));

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeAiCommitModal();
        }, true);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const m = document.getElementById('aiCommitModal');
                if (m && !m.classList.contains('hidden')) closeAiCommitModal();
            }
        }, true);
    }

    const stashSelect = document.getElementById('gitStashRepoSelect');
    const stashCreateBtn = document.getElementById('gitStashCreateBtn');
    if (stashSelect) {
        stashSelect.addEventListener('change', (e) => {
            const val = e.target.value;
            if (stashCreateBtn) stashCreateBtn.disabled = !val;
            loadGitStashes(val);
        });
    }

    const conflictModal = document.getElementById('gitConflictModal');
    const conflictCloseBtn = document.getElementById('gitConflictModalClose');
    const conflictCancelBtn = document.getElementById('gitConflictModalCancel');
    const hideConflictModal = () => { if (conflictModal) conflictModal.classList.add('hidden'); };
    if (conflictCloseBtn) conflictCloseBtn.addEventListener('click', hideConflictModal);
    if (conflictCancelBtn) conflictCancelBtn.addEventListener('click', hideConflictModal);
    if (conflictModal) {
        conflictModal.addEventListener('click', (e) => {
            if (e.target === conflictModal) hideConflictModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !conflictModal.classList.contains('hidden')) {
                hideConflictModal();
            }
        });
    }
})();

window.loadGitStashes = async (repoPath) => {
    const list = document.getElementById('gitStashList');
    const createBtn = document.getElementById('gitStashCreateBtn');
    if (!list) return;

    if (!repoPath) {
        list.innerHTML = '<div style="color: #718096; padding: 8px; text-align: center;">Select a repository above to view stashes.</div>';
        if (createBtn) createBtn.disabled = true;
        return;
    }

    if (createBtn) createBtn.disabled = false;
    list.innerHTML = '<div style="color: #718096; padding: 8px; text-align: center;">Loading stashes…</div>';

    try {
        const res = await fetch(apiUrl(`/api/git/stashes?repoPath=${encodeURIComponent(repoPath)}`));
        const data = await res.json();
        if (!data.success) {
            list.innerHTML = `<div style="color: #ef4444; padding: 8px; text-align: center;">Error: ${escapeHtml(data.error)}</div>`;
            return;
        }

        if (!Array.isArray(data.stashes) || data.stashes.length === 0) {
            list.innerHTML = '<div style="color: #718096; padding: 8px; text-align: center;">No stashes found in this repository.</div>';
            return;
        }

        list.innerHTML = data.stashes.map(stash => {
            return `
                <div class="git-repo-item" style="display:flex; justify-content:space-between; align-items:center; border: 1px solid #1c2759; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 10px; gap: 10px;">
                    <div style="display:flex; flex-direction:column; gap:4px; flex:1;">
                        <span style="font-family:'JetBrains Mono',monospace; color:#8ab4ff; font-weight:600; font-size:11.5px;">${escapeHtml(stash.ref)}</span>
                        <span style="color:#cbd5e1; font-size:11px; word-break:break-all;">${escapeHtml(stash.description)}</span>
                    </div>
                    <div style="display:flex; gap:6px;">
                        <button class="api-btn small" style="margin: 0; padding: 4px 8px; font-size: 11px; height: 26px;" onclick="applyGitStash(event, '${escapeHtml(repoPath)}', '${escapeHtml(stash.ref)}')">Apply</button>
                        <button class="api-btn small danger" style="margin: 0; padding: 4px 8px; font-size: 11px; height: 26px; background:#e53e3e; border-color:#e53e3e;" onclick="dropGitStash(event, '${escapeHtml(repoPath)}', '${escapeHtml(stash.ref)}')">Drop</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        list.innerHTML = `<div style="color: #ef4444; padding: 8px; text-align: center;">Error: ${escapeHtml(err.message)}</div>`;
    }
};

window.createGitStash = async () => {
    const stashSelect = document.getElementById('gitStashRepoSelect');
    if (!stashSelect || !stashSelect.value) return;
    const repoPath = stashSelect.value;
    const message = prompt("Enter an optional stash description / message:");
    if (message === null) return; // User cancelled

    const btn = document.getElementById('gitStashCreateBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Stashing...";

    try {
        const res = await fetch(apiUrl('/api/git/stash/create'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, message, includeUntracked: true })
        });
        const data = await res.json();
        if (!data.success) {
            alert("❌ Failed to create stash: " + data.error);
            return;
        }
        showGitflowToast("Stash Created", "Your local changes have been stashed successfully.");
        loadGitStashes(repoPath);
        loadGitRepos(true); // Refresh repository dirty indicators
    } catch (err) {
        alert("❌ Error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.applyGitStash = async (event, repoPath, ref) => {
    const btn = event.target;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Applying...";

    try {
        const res = await fetch(apiUrl('/api/git/stash/apply'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, ref })
        });
        const data = await res.json();
        if (!data.success) {
            alert("❌ Failed to apply stash: " + data.error);
            return;
        }
        showGitflowToast("Stash Applied", `Stash ${ref} applied successfully.`);
        loadGitStashes(repoPath);
        loadGitRepos(true);
    } catch (err) {
        alert("❌ Error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.dropGitStash = async (event, repoPath, ref) => {
    const confirmDrop = confirm(`Are you sure you want to drop stash "${ref}"?\nThis is a destructive action and cannot be undone.`);
    if (!confirmDrop) return;

    const btn = event.target;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Dropping...";

    try {
        const res = await fetch(apiUrl('/api/git/stash/drop'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, ref })
        });
        const data = await res.json();
        if (!data.success) {
            alert("❌ Failed to drop stash: " + data.error);
            return;
        }
        showGitflowToast("Stash Dropped", `Stash ${ref} has been removed.`);
        loadGitStashes(repoPath);
    } catch (err) {
        alert("❌ Error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.openConflictModal = async (repoPath) => {
    const modal = document.getElementById('gitConflictModal');
    const list = document.getElementById('gitConflictFileList');
    if (!modal || !list) return;

    list.innerHTML = '<div style="color: #718096; padding: 12px; text-align: center;">Retrieving conflicting files…</div>';
    modal.classList.remove('hidden');

    try {
        const res = await fetch(apiUrl(`/api/git/conflicts?repoPath=${encodeURIComponent(repoPath)}`));
        const data = await res.json();
        if (!data.success) {
            list.innerHTML = `<div style="color: #ef4444; padding: 12px; text-align: center;">Error: ${escapeHtml(data.error)}</div>`;
            return;
        }

        if (!Array.isArray(data.conflicts) || data.conflicts.length === 0) {
            list.innerHTML = '<div style="color: #48bb78; padding: 12px; text-align: center; font-weight:600;">🎉 No unmerged conflicts found!</div>';
            return;
        }

        list.innerHTML = data.conflicts.map(file => {
            return `
                <div class="git-repo-item" style="display:flex; justify-content:space-between; align-items:center; border: 1px solid #1e295d; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 10px; gap: 10px;">
                    <div style="display:flex; flex-direction:column; gap:4px; flex:1; min-width:0;">
                        <span style="font-family:'JetBrains Mono',monospace; color:#cbd5e1; font-size:11.5px; word-break:break-all;" title="${escapeHtml(file)}">${escapeHtml(PathBasename(file))}</span>
                        <span style="color:#718096; font-size:10px; word-break:break-all;">${escapeHtml(file)}</span>
                    </div>
                    <div style="display:flex; gap:6px;">
                        <button class="api-btn small btn-ours" style="margin: 0; padding: 4px 8px; font-size: 11px; height: 26px;" onclick="resolveConflict('${escapeHtml(repoPath)}', '${escapeHtml(file)}', 'ours', event)">Ours (Keep Local)</button>
                        <button class="api-btn small primary btn-theirs" style="margin: 0; padding: 4px 8px; font-size: 11px; height: 26px; background:#4299e1; border-color:#4299e1;" onclick="resolveConflict('${escapeHtml(repoPath)}', '${escapeHtml(file)}', 'theirs', event)">Theirs (Take Incoming)</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        list.innerHTML = `<div style="color: #ef4444; padding: 12px; text-align: center;">Error: ${escapeHtml(err.message)}</div>`;
    }
};

window.resolveConflict = async (repoPath, file, strategy, event) => {
    const btn = event.currentTarget || event.target;
    const container = btn.parentElement;
    const oursBtn = container.querySelector('.btn-ours');
    const theirsBtn = container.querySelector('.btn-theirs');

    if (oursBtn) oursBtn.disabled = true;
    if (theirsBtn) theirsBtn.disabled = true;
    btn.textContent = strategy === 'ours' ? 'Choosing Ours...' : 'Choosing Theirs...';

    try {
        const res = await fetch(apiUrl('/api/git/conflict/resolve'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath, file, strategy })
        });
        const data = await res.json();
        if (!data.success) {
            alert("❌ Failed to resolve conflict: " + data.error);
            if (oursBtn) oursBtn.disabled = false;
            if (theirsBtn) theirsBtn.disabled = false;
            btn.textContent = strategy === 'ours' ? 'Ours (Keep Local)' : 'Theirs (Take Incoming)';
            return;
        }

        // Remove file row from list
        const row = btn.closest('.git-repo-item');
        if (row) row.remove();

        // Check if all conflicts resolved
        const list = document.getElementById('gitConflictFileList');
        if (list && list.querySelectorAll('.git-repo-item').length === 0) {
            list.innerHTML = '<div style="color: #48bb78; padding: 12px; text-align: center; font-weight:600;">🎉 All conflicts resolved successfully!</div>';
            showGitflowToast("Conflicts Resolved", "All merge conflicts have been successfully resolved. You can now commit and merge.");
            setTimeout(() => {
                const modal = document.getElementById('gitConflictModal');
                if (modal) modal.classList.add('hidden');
                loadGitRepos(true);
            }, 1500);
        }
    } catch (err) {
        alert("❌ Error: " + err.message);
        if (oursBtn) oursBtn.disabled = false;
        if (theirsBtn) theirsBtn.disabled = false;
        btn.textContent = strategy === 'ours' ? 'Ours (Keep Local)' : 'Theirs (Take Incoming)';
    }
};

function PathBasename(p) {
    const s = String(p || '');
    const parts = s.split(/[/\\]/);
    return parts[parts.length - 1] || s;
}

// ==============================================================================
// ⌨️ Keyboard Shortcuts, Repository Search, and Standup Summary
// ==============================================================================

function initRepoSearchAndFilter() {
    const searchInput = document.getElementById('gitRepoSearchInput');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        const query = (e.target.value || '').toLowerCase().trim();
        filterRepositories(query);
    });

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            searchInput.value = '';
            filterRepositories('');
            searchInput.blur();
        }
    });
}

function filterRepositories(query) {
    const q = (query || '').toLowerCase().trim();
    const cards = document.querySelectorAll('.compact-app-card, .git-repo');
    
    cards.forEach(card => {
        if (!q) {
            card.style.display = '';
            return;
        }
        const text = (card.textContent || '').toLowerCase();
        const path = (card.getAttribute('data-repo-path-enc') || '').toLowerCase();
        const matches = text.includes(q) || path.includes(q);
        card.style.display = matches ? '' : 'none';
    });

    // Check sections and toggle visibility if all children are hidden
    ['gitRepoListApps', 'gitRepoListPackages', 'gitRepoListFavorites'].forEach(id => {
        const list = document.getElementById(id);
        if (!list) return;
        const section = list.closest('.git-section');
        if (!section) return;
        if (!q) {
            section.style.display = '';
            return;
        }
        const hasVisible = Array.from(list.children).some(c => c.style.display !== 'none');
        section.style.display = hasVisible ? '' : 'none';
    });
}

function copyStandupSummary() {
    const repos = Array.isArray(_gitLastRenderedRepos) ? _gitLastRenderedRepos : [];
    const workspacePath = document.getElementById('currentWorkspacePath')?.textContent || 'Current Workspace';
    const cleanWorkspace = workspacePath === 'Loading...' ? 'Workspace' : PathBasename(workspacePath);

    if (repos.length === 0) {
        showGitflowToast('Standup Summary', 'No repositories loaded yet.');
        return;
    }

    const dirtyRepos = [];
    const cleanRepos = [];

    repos.forEach(r => {
        const name = r.name || PathBasename(r.path);
        const branch = r.head || r.currentBranch || 'unknown';
        const isDirty = !!(r.isDirty || r.dirtyFilesCount > 0 || r.hasUncommittedChanges);
        const ahead = Number(r.ahead || 0);
        const behind = Number(r.behind || 0);

        let details = [];
        if (isDirty) {
            const count = r.dirtyFilesCount || 'uncommitted';
            details.push(`${count} modified/untracked files`);
        }
        if (ahead > 0) details.push(`ahead by ${ahead}`);
        if (behind > 0) details.push(`behind by ${behind}`);

        const detailStr = details.length > 0 ? ` (${details.join(', ')})` : '';

        if (isDirty || ahead > 0 || behind > 0) {
            dirtyRepos.push(`- **\`${name}\`** \`[${branch}]\`${detailStr}`);
        } else {
            cleanRepos.push(`- **\`${name}\`** \`[${branch}]\``);
        }
    });

    let md = `### 🚀 Git Standup Summary — ${cleanWorkspace}\n\n`;
    md += `**Total Repositories:** ${repos.length} (${dirtyRepos.length} with pending changes)\n\n`;

    if (dirtyRepos.length > 0) {
        md += `#### ⚠️ Active / Pending Repositories:\n`;
        md += dirtyRepos.join('\n') + '\n\n';
    }

    if (cleanRepos.length > 0) {
        md += `#### 🟢 Clean & Synced Repositories:\n`;
        md += cleanRepos.join('\n') + '\n';
    }

    navigator.clipboard.writeText(md.trim()).then(() => {
        showGitflowToast('📋 Copied to Clipboard', `Standup summary for ${repos.length} repositories copied!`);
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
        showGitflowToast('Copy Failed', 'Could not copy to clipboard. Check browser permissions.');
    });
}

function openShortcutsModal() {
    const modal = document.getElementById('gitShortcutsModal');
    if (modal) modal.classList.remove('hidden');
}

function closeShortcutsModal() {
    const modal = document.getElementById('gitShortcutsModal');
    if (modal) modal.classList.add('hidden');
}

function initKeyboardShortcuts() {
    const shortcutsBtn = document.getElementById('gitShortcutsHelpBtn');
    const shortcutsClose = document.getElementById('gitShortcutsClose');
    const shortcutsOk = document.getElementById('gitShortcutsOk');
    const copyStandupBtn = document.getElementById('gitCopyStandupBtn');

    if (shortcutsBtn) shortcutsBtn.addEventListener('click', openShortcutsModal);
    if (shortcutsClose) shortcutsClose.addEventListener('click', closeShortcutsModal);
    if (shortcutsOk) shortcutsOk.addEventListener('click', closeShortcutsModal);
    if (copyStandupBtn) copyStandupBtn.addEventListener('click', copyStandupSummary);

    window.addEventListener('keydown', (e) => {
        const active = document.activeElement;
        const isTyping = active && (
            active.tagName === 'INPUT' ||
            active.tagName === 'TEXTAREA' ||
            active.isContentEditable ||
            active.tagName === 'SELECT'
        );

        // 1. Esc: Always works to dismiss active modal, popover, or clear search
        if (e.key === 'Escape') {
            if (isTyping && active.id === 'gitRepoSearchInput') {
                active.value = '';
                filterRepositories('');
                active.blur();
                return;
            }

            // Close shortcuts modal if open
            const shortcutsModal = document.getElementById('gitShortcutsModal');
            if (shortcutsModal && !shortcutsModal.classList.contains('hidden')) {
                e.preventDefault();
                closeShortcutsModal();
                return;
            }

            // Close any open modal
            const openModals = Array.from(document.querySelectorAll('.modal:not(.hidden), .ui-modal-backdrop:not(.hidden)'));
            if (openModals.length > 0) {
                e.preventDefault();
                openModals[openModals.length - 1].classList.add('hidden');
                return;
            }

            // Close popover
            const popover = document.getElementById('gitBranchPopover');
            if (popover && !popover.classList.contains('hidden')) {
                e.preventDefault();
                popover.classList.add('hidden');
                return;
            }
        }

        // 2. Ctrl+K or Cmd+K -> Focus Repo Search (even if focused elsewhere)
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            const searchInput = document.getElementById('gitRepoSearchInput');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
            return;
        }

        // 3. Single key hotkeys (active only when NOT typing in an input field)
        if (!isTyping) {
            if (e.key === '/') {
                e.preventDefault();
                const searchInput = document.getElementById('gitRepoSearchInput');
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
                return;
            }

            if (e.key.toLowerCase() === 'r' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                const refreshBtn = document.getElementById('gitRefreshReposBtn');
                if (refreshBtn) refreshBtn.click();
                return;
            }

            if (e.key.toLowerCase() === 'f' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                const fetchBtn = document.getElementById('gitFetchAllBtn');
                if (fetchBtn) fetchBtn.click();
                return;
            }

            if (e.key.toLowerCase() === 'c' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                copyStandupSummary();
                return;
            }

            if (e.key.toLowerCase() === 'w' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                const switchBtn = document.getElementById('gitSwitchWorkspaceBtn');
                if (switchBtn) switchBtn.click();
                return;
            }

            if (e.key === '?') {
                e.preventDefault();
                openShortcutsModal();
                return;
            }
        }
    });
}

// Auto-initialize search and keyboard listeners on load
initRepoSearchAndFilter();
initKeyboardShortcuts();
