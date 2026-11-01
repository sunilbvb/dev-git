// ==========================================
// DevGit — Repository Doctor & Health Panel
// ==========================================

let _currentDoctorRepo = null;

async function openDoctorModal(repoPath) {
    _currentDoctorRepo = repoPath || (window.selectedRepoPath || '');
    if (!_currentDoctorRepo) {
        showToast('Please select a repository first', 'error');
        return;
    }

    let modal = document.getElementById('devgitDoctorModal');
    if (!modal) {
        createDoctorModalDom();
        modal = document.getElementById('devgitDoctorModal');
    }

    const titleEl = document.getElementById('doctorModalRepoName');
    if (titleEl) {
        titleEl.textContent = _currentDoctorRepo.split('/').pop() || _currentDoctorRepo;
    }

    modal.classList.remove('hidden');
    await runDoctorAudit();
}

function closeDoctorModal() {
    const modal = document.getElementById('devgitDoctorModal');
    if (modal) modal.classList.add('hidden');
}

async function runDoctorAudit() {
    const container = document.getElementById('doctorResultsContainer');
    const badge = document.getElementById('doctorHealthBadge');
    if (!container) return;

    container.innerHTML = '<div style="color:#94a3b8; font-size:13px; padding:20px; text-align:center;">Running repository diagnostics...</div>';
    if (badge) badge.style.display = 'none';

    try {
        const res = await fetch(apiUrl(`/api/git/doctor?repoPath=${encodeURIComponent(_currentDoctorRepo)}`));
        const data = await res.json();
        if (!data.success) {
            container.innerHTML = `<div style="color:#ef4444; font-size:13px; padding:20px;">${escapeHtml(data.error)}</div>`;
            return;
        }

        if (badge) {
            badge.style.display = 'inline-block';
            if (data.health === 'healthy') {
                badge.textContent = 'HEALTHY';
                badge.style.background = '#10b981';
                badge.style.color = '#ffffff';
            } else if (data.health === 'warning') {
                badge.textContent = `${data.warningCount} WARNING(S)`;
                badge.style.background = '#f59e0b';
                badge.style.color = '#000000';
            } else {
                badge.textContent = `${data.errorCount} ISSUE(S)`;
                badge.style.background = '#ef4444';
                badge.style.color = '#ffffff';
            }
        }

        const checks = data.checks || [];
        let html = '<div style="display:flex; flex-direction:column; gap:10px;">';
        checks.forEach(c => {
            let icon = '✅';
            let borderColor = 'rgba(16,185,129,0.3)';
            let titleColor = '#10b981';
            if (c.type === 'warning') {
                icon = '⚠️';
                borderColor = 'rgba(245,158,11,0.3)';
                titleColor = '#f59e0b';
            } else if (c.type === 'error') {
                icon = '❌';
                borderColor = 'rgba(239,68,68,0.3)';
                titleColor = '#ef4444';
            }

            let actionBtn = '';
            if (c.fixable && c.action === 'delete_merged_branches' && Array.isArray(c.details)) {
                actionBtn = `
                    <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;">
                        ${c.details.map(b => `
                            <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="runDoctorFix('delete_branch', '${escapeHtml(b)}')">Delete '${escapeHtml(b)}'</button>
                        `).join('')}
                    </div>
                `;
            } else if (c.fixable && c.action === 'push_tags') {
                actionBtn = `
                    <button class="ui-button" data-variant="primary" data-size="sm" type="button" style="margin-top:8px;" onclick="runDoctorFix('push_tags')">Push Tags to Origin</button>
                `;
            }

            html += `
                <div style="background:rgba(255,255,255,0.02); border:1px solid ${borderColor}; border-radius:6px; padding:12px 14px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span>${icon}</span>
                        <span style="font-size:13px; font-weight:700; color:${titleColor};">${escapeHtml(c.title)}</span>
                    </div>
                    <div style="font-size:12px; color:#cbd5e1; margin-top:4px;">${escapeHtml(c.message)}</div>
                    ${actionBtn}
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<div style="color:#ef4444; font-size:13px; padding:20px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

async function runDoctorFix(action, item) {
    try {
        const res = await fetch(apiUrl('/api/git/doctor/fix'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _currentDoctorRepo,
                action: action,
                item: item
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || 'Fixed', 'success');
            await runDoctorAudit();
            if (typeof loadGitRepos === 'function') loadGitRepos(false);
        } else {
            showToast(data.error || 'Fix failed', 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    }
}

function createDoctorModalDom() {
    const modal = document.createElement('div');
    modal.id = 'devgitDoctorModal';
    modal.className = 'ui-modal-backdrop hidden';
    modal.style.zIndex = '99999';

    modal.innerHTML = `
        <div class="ui-modal" style="max-width: 680px; width: 95%; max-height: 90vh;">
            <div class="ui-modal-header" style="display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:18px;">🩺</span>
                    <h3 class="ui-modal-title">Repository Doctor — <span id="doctorModalRepoName"></span></h3>
                    <span id="doctorHealthBadge" style="font-size:10px; font-weight:700; padding:2px 8px; border-radius:4px; display:none;"></span>
                </div>
                <button type="button" class="ui-modal-close" onclick="closeDoctorModal()">&times;</button>
            </div>
            <div class="ui-modal-body" style="padding:16px; overflow-y:auto; max-height:68vh;">
                <div id="doctorResultsContainer"></div>
            </div>
            <div class="ui-modal-footer" style="display:flex; justify-content:space-between;">
                <button class="ui-button" data-variant="secondary" data-size="sm" type="button" onclick="runDoctorAudit()">Re-check</button>
                <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="closeDoctorModal()">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}
