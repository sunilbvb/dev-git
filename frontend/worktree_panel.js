// ==========================================
// DevGit — Worktree Manager Panel
// ==========================================

let _currentWorktreeRepo = null;

async function openWorktreesModal(repoPath) {
    _currentWorktreeRepo = repoPath || (window.selectedRepoPath || '');
    if (!_currentWorktreeRepo) {
        showToast('Please select a repository first', 'error');
        return;
    }

    let modal = document.getElementById('devgitWorktreeModal');
    if (!modal) {
        createWorktreeModalDom();
        modal = document.getElementById('devgitWorktreeModal');
    }

    const titleEl = document.getElementById('worktreeModalRepoName');
    if (titleEl) {
        titleEl.textContent = _currentWorktreeRepo.split('/').pop() || _currentWorktreeRepo;
    }

    modal.classList.remove('hidden');
    await loadWorktreesList();
}

function closeWorktreesModal() {
    const modal = document.getElementById('devgitWorktreeModal');
    if (modal) modal.classList.add('hidden');
}

async function loadWorktreesList() {
    const listEl = document.getElementById('worktreeListContainer');
    if (!listEl) return;
    listEl.innerHTML = '<div style="color: #94a3b8; font-size: 13px; padding: 12px 0;">Loading worktrees...</div>';

    try {
        const res = await fetch(apiUrl(`/api/git/worktrees?repoPath=${encodeURIComponent(_currentWorktreeRepo)}`));
        const data = await res.json();
        if (!data.success) {
            listEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">${escapeHtml(data.error || 'Failed to load worktrees')}</div>`;
            return;
        }

        const trees = data.worktrees || [];
        if (trees.length === 0) {
            listEl.innerHTML = '<div style="color: #64748b; font-size: 13px; padding: 12px 0;">No active worktrees found.</div>';
            return;
        }

        let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
        trees.forEach(t => {
            const isMain = t.isMainWorktree;
            html += `
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                    <div style="display: flex; flex-direction: column; gap: 3px; min-width: 0;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-weight: 600; font-size: 13px; color: #f8fafc; font-family: monospace;">${escapeHtml(t.path)}</span>
                            ${isMain ? '<span style="font-size: 10px; background: #3b82f6; color: #fff; padding: 2px 6px; border-radius: 4px; font-weight: 600;">MAIN</span>' : '<span style="font-size: 10px; background: rgba(255,255,255,0.1); color: #cbd5e1; padding: 2px 6px; border-radius: 4px;">LINKED</span>'}
                        </div>
                        <div style="font-size: 12px; color: #94a3b8;">
                            Branch: <strong style="color: #38bdf8;">${escapeHtml(t.branch || 'detached')}</strong> &bull; Commit: <code style="color: #cbd5e1;">${escapeHtml((t.head || '').substring(0, 7))}</code>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
                        ${!isMain ? `
                            <button class="ui-button" data-variant="danger" data-size="sm" type="button" onclick="removeWorktree('${escapeHtml(t.path)}')">Remove</button>
                        ` : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
        listEl.innerHTML = html;
    } catch (err) {
        listEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function addWorktreeFromForm() {
    const pathInput = document.getElementById('newWorktreePath');
    const branchInput = document.getElementById('newWorktreeBranch');
    const createBranchCheckbox = document.getElementById('newWorktreeCreateBranch');

    const path = (pathInput ? pathInput.value : '').trim();
    const branch = (branchInput ? branchInput.value : '').trim();
    const createNew = createBranchCheckbox ? createBranchCheckbox.checked : false;

    if (!path) {
        showToast('Please specify a destination path for the worktree', 'error');
        return;
    }

    try {
        const payload = {
            repoPath: _currentWorktreeRepo,
            worktreePath: path,
            branch: branch || undefined,
            createBranch: createNew
        };
        const res = await fetch(apiUrl('/api/git/worktree/add'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast('Worktree added successfully', 'success');
            if (pathInput) pathInput.value = '';
            if (branchInput) branchInput.value = '';
            loadWorktreesList();
        } else {
            showToast(data.error || 'Failed to add worktree', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

async function removeWorktree(worktreePath) {
    if (!confirm(`Are you sure you want to remove worktree at:\n${worktreePath}?`)) return;

    try {
        const res = await fetch(apiUrl('/api/git/worktree/remove'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath: _currentWorktreeRepo, worktreePath })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Worktree removed', 'success');
            loadWorktreesList();
        } else {
            showToast(data.error || 'Failed to remove worktree', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

async function pruneWorktrees() {
    try {
        const res = await fetch(apiUrl('/api/git/worktree/prune'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath: _currentWorktreeRepo })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Stale worktrees pruned', 'success');
            loadWorktreesList();
        } else {
            showToast(data.error || 'Failed to prune', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

function createWorktreeModalDom() {
    const modal = document.createElement('div');
    modal.id = 'devgitWorktreeModal';
    modal.className = 'ui-modal-backdrop hidden';
    modal.style.zIndex = '99999';

    modal.innerHTML = `
        <div class="ui-modal" style="max-width: 680px; width: 95%;">
            <div class="ui-modal-header" style="display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">🌲</span>
                    <h3 class="ui-modal-title">Worktree Manager — <span id="worktreeModalRepoName"></span></h3>
                </div>
                <button type="button" class="ui-modal-close" onclick="closeWorktreesModal()">&times;</button>
            </div>
            <div class="ui-modal-body" style="display: flex; flex-direction: column; gap: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">Active Linked Worktrees</span>
                    <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="pruneWorktrees()">Prune Stale</button>
                </div>
                <div id="worktreeListContainer"></div>

                <div style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px;">
                    <span style="font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">Add Linked Worktree</span>
                    <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 8px;">
                        <input type="text" id="newWorktreePath" class="ui-input" placeholder="Absolute or relative path (e.g. ../my-feature-tree)" style="font-size: 12px;" />
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <input type="text" id="newWorktreeBranch" class="ui-input" placeholder="Branch name (optional)" style="flex: 1; font-size: 12px;" />
                            <label style="font-size: 12px; color: #cbd5e1; display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                <input type="checkbox" id="newWorktreeCreateBranch" /> Create new branch
                            </label>
                            <button class="ui-button" data-variant="primary" data-size="sm" type="button" onclick="addWorktreeFromForm()">Add Worktree</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="ui-modal-footer">
                <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="closeWorktreesModal()">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}
