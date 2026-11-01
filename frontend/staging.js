// ==========================================
// DevGit — File-Level Staging Manager
// ==========================================

let _currentStagingRepo = null;

async function openStagingModal(repoPath) {
    _currentStagingRepo = repoPath || (window.selectedRepoPath || '');
    if (!_currentStagingRepo) {
        showToast('Please select a repository first', 'error');
        return;
    }

    let modal = document.getElementById('devgitStagingModal');
    if (!modal) {
        createStagingModalDom();
        modal = document.getElementById('devgitStagingModal');
    }

    const titleEl = document.getElementById('stagingModalRepoName');
    if (titleEl) {
        titleEl.textContent = _currentStagingRepo.split('/').pop() || _currentStagingRepo;
    }

    modal.classList.remove('hidden');
    await loadStagingFiles();
}

function closeStagingModal() {
    const modal = document.getElementById('devgitStagingModal');
    if (modal) modal.classList.add('hidden');
}

async function loadStagingFiles() {
    const stagedContainer = document.getElementById('stagedFilesContainer');
    const unstagedContainer = document.getElementById('unstagedFilesContainer');
    if (!stagedContainer || !unstagedContainer) return;

    stagedContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:6px 0;">Loading...</div>';
    unstagedContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:6px 0;">Loading...</div>';

    try {
        const res = await fetch(apiUrl(`/api/git/files?repoPath=${encodeURIComponent(_currentStagingRepo)}`));
        const data = await res.json();
        if (!data.success) {
            stagedContainer.innerHTML = `<div style="color:#ef4444; font-size:12px;">${escapeHtml(data.error)}</div>`;
            unstagedContainer.innerHTML = '';
            return;
        }

        const staged = data.staged || [];
        const unstaged = (data.unstaged || []).concat(data.untracked || []);

        // Render staged files
        if (staged.length === 0) {
            stagedContainer.innerHTML = '<div style="color:#64748b; font-size:12px; padding:8px 0;">No staged changes.</div>';
        } else {
            let html = '<div style="display:flex; flex-direction:column; gap:4px;">';
            staged.forEach(f => {
                html += `
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 10px; background:rgba(16,185,129,0.06); border:1px solid rgba(16,185,129,0.2); border-radius:4px;">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span style="font-size:10px; font-weight:700; color:#10b981; background:rgba(16,185,129,0.2); padding:1px 5px; border-radius:3px;">${escapeHtml(f.status)}</span>
                            <span style="font-size:12px; font-family:monospace; color:#f1f5f9;">${escapeHtml(f.path)}</span>
                        </div>
                        <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="performStagingAction(['${escapeHtml(f.path)}'], 'unstage')">Unstage</button>
                    </div>
                `;
            });
            html += '</div>';
            stagedContainer.innerHTML = html;
        }

        // Render unstaged / untracked files
        if (unstaged.length === 0) {
            unstagedContainer.innerHTML = '<div style="color:#64748b; font-size:12px; padding:8px 0;">No unstaged changes.</div>';
        } else {
            let html = '<div style="display:flex; flex-direction:column; gap:4px;">';
            unstaged.forEach(f => {
                const isUntracked = f.status === '?';
                html += `
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 10px; background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:4px;">
                        <div style="display:flex; align-items:center; gap:8px;">
                            <span style="font-size:10px; font-weight:700; color:${isUntracked ? '#94a3b8' : '#eab308'}; background:rgba(255,255,255,0.08); padding:1px 5px; border-radius:3px;">${escapeHtml(f.status)}</span>
                            <span style="font-size:12px; font-family:monospace; color:#f1f5f9;">${escapeHtml(f.path)}</span>
                        </div>
                        <div style="display:flex; gap:6px;">
                            <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="performStagingAction(['${escapeHtml(f.path)}'], 'stage')">Stage (+)</button>
                            <button class="ui-button" data-variant="danger" data-size="sm" type="button" onclick="performStagingAction(['${escapeHtml(f.path)}'], 'discard')">Discard</button>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            unstagedContainer.innerHTML = html;
        }
    } catch (err) {
        stagedContainer.innerHTML = `<div style="color:#ef4444; font-size:12px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function performStagingAction(files, action) {
    if (action === 'discard' && !confirm(`Discard changes to:\n${files.join('\n')}? This cannot be undone.`)) {
        return;
    }

    try {
        const payload = {
            repoPath: _currentStagingRepo,
            action: action,
            files: files
        };
        const res = await fetch(apiUrl('/api/git/stage'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || 'Updated', 'success');
            await loadStagingFiles();
            if (typeof loadGitRepos === 'function') loadGitRepos(false);
        } else {
            showToast(data.error || 'Failed staging operation', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

function createStagingModalDom() {
    const modal = document.createElement('div');
    modal.id = 'devgitStagingModal';
    modal.className = 'ui-modal-backdrop hidden';
    modal.style.zIndex = '99999';

    modal.innerHTML = `
        <div class="ui-modal" style="max-width: 720px; width: 95%; max-height: 90vh;">
            <div class="ui-modal-header" style="display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:18px;">📋</span>
                    <h3 class="ui-modal-title">File Staging & Changes — <span id="stagingModalRepoName"></span></h3>
                </div>
                <button type="button" class="ui-modal-close" onclick="closeStagingModal()">&times;</button>
            </div>
            <div class="ui-modal-body" style="display:flex; flex-direction:column; gap:16px; overflow-y:auto;">
                <!-- Staged Section -->
                <div>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                        <span style="font-size:12px; font-weight:700; color:#10b981; text-transform:uppercase;">Staged Changes</span>
                        <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="performStagingAction([], 'unstage_all')">Unstage All</button>
                    </div>
                    <div id="stagedFilesContainer"></div>
                </div>

                <!-- Unstaged Section -->
                <div style="border-top:1px solid rgba(255,255,255,0.08); padding-top:16px;">
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                        <span style="font-size:12px; font-weight:700; color:#eab308; text-transform:uppercase;">Unstaged & Untracked</span>
                        <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="performStagingAction([], 'stage_all')">Stage All (+)</button>
                    </div>
                    <div id="unstagedFilesContainer"></div>
                </div>
            </div>
            <div class="ui-modal-footer">
                <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="closeStagingModal()">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}
