// ==========================================
// DevGit — Conflict Resolver Panel
// ==========================================

let _currentConflictRepo = null;
let _currentConflictFile = null;

async function openConflictsModal(repoPath) {
    _currentConflictRepo = repoPath || (window.selectedRepoPath || '');
    if (!_currentConflictRepo) {
        showToast('Please select a repository first', 'error');
        return;
    }

    let modal = document.getElementById('devgitConflictModal');
    if (!modal) {
        createConflictModalDom();
        modal = document.getElementById('devgitConflictModal');
    }

    const titleEl = document.getElementById('conflictModalRepoName');
    if (titleEl) {
        titleEl.textContent = _currentConflictRepo.split('/').pop() || _currentConflictRepo;
    }

    modal.classList.remove('hidden');
    await loadConflictsList();
}

function closeConflictsModal() {
    const modal = document.getElementById('devgitConflictModal');
    if (modal) modal.classList.add('hidden');
}

async function loadConflictsList() {
    const listEl = document.getElementById('conflictFilesList');
    const editorEl = document.getElementById('conflictEditorContainer');
    if (!listEl) return;

    listEl.innerHTML = '<div style="color: #94a3b8; font-size: 13px; padding: 8px 0;">Scanning for conflicts...</div>';
    if (editorEl) editorEl.style.display = 'none';

    try {
        const res = await fetch(apiUrl(`/api/git/conflicts?repoPath=${encodeURIComponent(_currentConflictRepo)}`));
        const data = await res.json();
        if (!data.success) {
            listEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">${escapeHtml(data.error || 'Failed to list conflicts')}</div>`;
            return;
        }

        const files = data.conflicts || [];
        const opBadge = document.getElementById('conflictOperationBadge');
        if (opBadge) {
            opBadge.textContent = data.operation !== 'none' ? `Active: ${data.operation.toUpperCase()}` : 'No operation active';
            opBadge.style.display = data.operation !== 'none' ? 'inline-block' : 'none';
        }

        if (files.length === 0) {
            listEl.innerHTML = '<div style="color: #10b981; font-size: 13px; padding: 12px 0;">✅ No unresolved merge or rebase conflicts!</div>';
            return;
        }

        let html = '<div style="display: flex; flex-direction: column; gap: 6px;">';
        files.forEach((f, idx) => {
            html += `
                <div onclick="selectConflictFile('${escapeHtml(f)}')" style="cursor: pointer; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 6px; padding: 8px 12px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="color: #ef4444;">⚠️</span>
                        <span style="font-size: 13px; font-weight: 600; color: #f8fafc; font-family: monospace;">${escapeHtml(f)}</span>
                    </div>
                    <span style="font-size: 11px; color: #94a3b8;">Click to inspect</span>
                </div>
            `;
        });
        html += '</div>';
        listEl.innerHTML = html;

        // Auto-select first file
        if (files.length > 0) {
            selectConflictFile(files[0]);
        }
    } catch (err) {
        listEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function selectConflictFile(filePath) {
    _currentConflictFile = filePath;
    const editorEl = document.getElementById('conflictEditorContainer');
    const headerEl = document.getElementById('currentConflictFileName');
    const blocksEl = document.getElementById('conflictBlocksContainer');
    if (!editorEl || !blocksEl) return;

    if (headerEl) headerEl.textContent = filePath;
    editorEl.style.display = 'flex';
    blocksEl.innerHTML = '<div style="color: #94a3b8; font-size: 13px; padding: 10px 0;">Reading file conflict blocks...</div>';

    try {
        const res = await fetch(apiUrl(`/api/git/conflicts/file?repoPath=${encodeURIComponent(_currentConflictRepo)}&file=${encodeURIComponent(filePath)}`));
        const data = await res.json();
        if (!data.success) {
            blocksEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">${escapeHtml(data.error)}</div>`;
            return;
        }

        const blocks = data.conflictBlocks || [];
        if (blocks.length === 0) {
            blocksEl.innerHTML = '<div style="color: #94a3b8; font-size: 13px;">No standard conflict markers found. Use custom resolution if needed.</div>';
            return;
        }

        let html = '';
        blocks.forEach((b, i) => {
            html += `
                <div style="border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; overflow: hidden; margin-bottom: 12px;">
                    <div style="background: rgba(37, 99, 235, 0.15); border-bottom: 1px solid rgba(37, 99, 235, 0.3); padding: 6px 10px; font-size: 11px; font-weight: 600; color: #60a5fa;">
                        CONFLICT HUNK #${i + 1}
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 10px; background: rgba(0,0,0,0.3);">
                        <div>
                            <div style="font-size: 11px; font-weight: 700; color: #34d399; margin-bottom: 4px;">OURS (Current Branch)</div>
                            <pre style="background: #0f172a; padding: 8px; border-radius: 4px; font-size: 12px; color: #f1f5f9; overflow-x: auto; max-height: 140px; margin: 0;">${escapeHtml(b.ours)}</pre>
                        </div>
                        <div>
                            <div style="font-size: 11px; font-weight: 700; color: #f87171; margin-bottom: 4px;">THEIRS (Incoming Branch)</div>
                            <pre style="background: #0f172a; padding: 8px; border-radius: 4px; font-size: 12px; color: #f1f5f9; overflow-x: auto; max-height: 140px; margin: 0;">${escapeHtml(b.theirs)}</pre>
                        </div>
                    </div>
                </div>
            `;
        });
        blocksEl.innerHTML = html;
    } catch (err) {
        blocksEl.innerHTML = `<div style="color: #ef4444; font-size: 13px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function resolveConflict(strategy) {
    if (!_currentConflictRepo || !_currentConflictFile) return;

    try {
        const res = await fetch(apiUrl('/api/git/conflict/resolve'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _currentConflictRepo,
                file: _currentConflictFile,
                strategy: strategy
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Resolved using ${strategy}`, 'success');
            await loadConflictsList();
        } else {
            showToast(data.error || 'Failed to resolve conflict', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

async function abortActiveConflictOperation() {
    if (!confirm('Are you sure you want to abort the merge or rebase? All uncommitted resolution work will be discarded.')) return;

    try {
        const res = await fetch(apiUrl('/api/git/conflict/abort'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repoPath: _currentConflictRepo })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || 'Operation aborted', 'info');
            closeConflictsModal();
            if (typeof loadGitRepos === 'function') loadGitRepos(true);
        } else {
            showToast(data.error || 'Failed to abort', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

function createConflictModalDom() {
    const modal = document.createElement('div');
    modal.id = 'devgitConflictModal';
    modal.className = 'ui-modal-backdrop hidden';
    modal.style.zIndex = '99999';

    modal.innerHTML = `
        <div class="ui-modal" style="max-width: 820px; width: 95%; max-height: 90vh;">
            <div class="ui-modal-header" style="display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 18px;">⚔️</span>
                    <h3 class="ui-modal-title">Merge & Rebase Conflict Resolver — <span id="conflictModalRepoName"></span></h3>
                    <span id="conflictOperationBadge" style="font-size: 11px; background: rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 2px 8px; border-radius: 4px; display: none;"></span>
                </div>
                <button type="button" class="ui-modal-close" onclick="closeConflictsModal()">&times;</button>
            </div>
            <div class="ui-modal-body" style="display: flex; flex-direction: column; gap: 14px; overflow-y: auto;">
                <div>
                    <span style="font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">Conflicted Files</span>
                    <div id="conflictFilesList" style="margin-top: 6px;"></div>
                </div>

                <div id="conflictEditorContainer" style="display: none; flex-direction: column; gap: 10px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 14px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                        <span style="font-size: 13px; font-weight: 600; color: #f8fafc;" id="currentConflictFileName"></span>
                        <div style="display: flex; gap: 8px;">
                            <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="resolveConflict('ours')">Keep Ours (Local)</button>
                            <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="resolveConflict('theirs')">Accept Theirs (Incoming)</button>
                        </div>
                    </div>
                    <div id="conflictBlocksContainer"></div>
                </div>
            </div>
            <div class="ui-modal-footer" style="display: flex; justify-content: space-between;">
                <button class="ui-button" data-variant="danger" data-size="sm" type="button" onclick="abortActiveConflictOperation()">Abort Merge/Rebase</button>
                <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="closeConflictsModal()">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}
