// ==========================================
// DevGit — Interactive Git DAG Graph
// ==========================================

let _currentGraphRepo = null;

async function openGitGraphModal(repoPath) {
    _currentGraphRepo = repoPath || (window.selectedRepoPath || '');
    if (!_currentGraphRepo) {
        showToast('Please select a repository first', 'error');
        return;
    }

    let modal = document.getElementById('devgitGraphModal');
    if (!modal) {
        createGraphModalDom();
        modal = document.getElementById('devgitGraphModal');
    }

    const titleEl = document.getElementById('graphModalRepoName');
    if (titleEl) {
        titleEl.textContent = _currentGraphRepo.split('/').pop() || _currentGraphRepo;
    }

    modal.classList.remove('hidden');
    await loadGitGraph();
}

function closeGitGraphModal() {
    const modal = document.getElementById('devgitGraphModal');
    if (modal) modal.classList.add('hidden');
}

async function loadGitGraph() {
    const container = document.getElementById('gitGraphCanvasContainer');
    if (!container) return;

    container.innerHTML = '<div style="color:#94a3b8; font-size:13px; padding:20px; text-align:center;">Rendering Git DAG topology...</div>';

    try {
        const res = await fetch(apiUrl(`/api/git/graph?repoPath=${encodeURIComponent(_currentGraphRepo)}&limit=60`));
        const data = await res.json();
        if (!data.success) {
            container.innerHTML = `<div style="color:#ef4444; font-size:13px; padding:20px;">${escapeHtml(data.error)}</div>`;
            return;
        }

        const commits = data.commits || [];
        if (commits.length === 0) {
            container.innerHTML = '<div style="color:#64748b; font-size:13px; padding:20px;">No commits found.</div>';
            return;
        }

        // Color palette for branches
        const laneColors = ['#38bdf8', '#34d399', '#f472b6', '#a78bfa', '#fbbf24', '#f87171', '#4ade80'];

        let html = '<div style="display:flex; flex-direction:column; gap:6px; font-family:monospace; font-size:12px;">';
        commits.forEach(c => {
            const color = laneColors[c.lane % laneColors.length];
            const laneOffset = c.lane * 18;

            let refBadges = '';
            (c.refs || []).forEach(r => {
                let badgeBg = 'rgba(255,255,255,0.1)';
                let badgeColor = '#cbd5e1';
                if (r.type === 'head') {
                    badgeBg = '#3b82f6';
                    badgeColor = '#ffffff';
                } else if (r.type === 'tag') {
                    badgeBg = '#f59e0b';
                    badgeColor = '#000000';
                } else if (r.type === 'remote') {
                    badgeBg = 'rgba(147, 51, 234, 0.3)';
                    badgeColor = '#c084fc';
                }
                refBadges += `<span style="background:${badgeBg}; color:${badgeColor}; font-size:10px; font-weight:700; padding:1px 6px; border-radius:4px; margin-right:4px;">${escapeHtml(r.name)}</span>`;
            });

            html += `
                <div style="display:flex; align-items:center; gap:10px; padding:4px 8px; border-radius:4px; background:rgba(255,255,255,0.015); hover:background:rgba(255,255,255,0.04);">
                    <!-- Node & Lane connector -->
                    <div style="width: 80px; display:flex; align-items:center; position:relative;">
                        <span style="display:inline-block; margin-left:${laneOffset}px; width:10px; height:10px; border-radius:50%; background:${color}; box-shadow:0 0 6px ${color};"></span>
                    </div>

                    <!-- Hash -->
                    <span style="color:#64748b; font-size:11px; width:58px; flex-shrink:0;">${escapeHtml(c.shortHash)}</span>

                    <!-- Refs & Subject -->
                    <div style="display:flex; align-items:center; gap:6px; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        ${refBadges}
                        <span style="color:#f8fafc; font-size:12px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(c.subject)}</span>
                    </div>

                    <!-- Author & Date -->
                    <div style="display:flex; align-items:center; gap:8px; flex-shrink:0; font-size:11px; color:#94a3b8;">
                        <span>${escapeHtml(c.author)}</span>
                        <span>&bull;</span>
                        <span style="color:#64748b;">${escapeHtml(c.date)}</span>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<div style="color:#ef4444; font-size:13px; padding:20px;">Error: ${escapeHtml(err.message)}</div>`;
    }
}

function createGraphModalDom() {
    const modal = document.createElement('div');
    modal.id = 'devgitGraphModal';
    modal.className = 'ui-modal-backdrop hidden';
    modal.style.zIndex = '99999';

    modal.innerHTML = `
        <div class="ui-modal" style="max-width: 860px; width: 95%; max-height: 90vh;">
            <div class="ui-modal-header" style="display:flex; align-items:center; justify-content:space-between;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:18px;">📊</span>
                    <h3 class="ui-modal-title">Git DAG Commit Graph — <span id="graphModalRepoName"></span></h3>
                </div>
                <button type="button" class="ui-modal-close" onclick="closeGitGraphModal()">&times;</button>
            </div>
            <div class="ui-modal-body" style="padding:14px; overflow-y:auto; max-height:68vh;">
                <div id="gitGraphCanvasContainer"></div>
            </div>
            <div class="ui-modal-footer">
                <button class="ui-button" data-variant="outline" data-size="sm" type="button" onclick="closeGitGraphModal()">Close</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}
