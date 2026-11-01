// Release All (develop -> main, tag, GitHub releases) and Sync develop (main -> develop back-merge) across repos.
// Backend: /api/git/release/all/preview (read-only) and /api/git/release/all/run (background job).
(function () {
    const modals = {};
    let pollTimer = null;

    const el = (tag, props = {}, children = []) => {
        const node = document.createElement(tag);
        Object.assign(node, props);
        children.forEach(c => node.append(c));
        return node;
    };
    const post = async (path, body) => {
        const res = await fetch(apiUrl(path), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...body, githubToken: localStorage.getItem('devgit_github_token_v1') || '' })
        });
        return res.json();
    };

    function build(mode) {
        const sync = mode === 'sync';
        const id = (n) => `ra_${mode}_${n}`;
        const state = { rows: [] };
        const g = (n) => document.getElementById(id(n));
        const field = (n, label, input) => el('label', { style: 'display:flex;flex-direction:column;gap:4px;font-size:12px;color:#94a3b8;' }, [label, input]);
        const btn = (text, variant, extra = {}) => { const b = el('button', { className: 'ui-button', type: 'button', textContent: text, ...extra }); b.dataset.variant = variant; return b; };

        const status = el('div', { id: id('status'), style: 'font-size:12px;color:#94a3b8;' });
        const list = el('div', { id: id('list'), style: 'display:flex;flex-direction:column;gap:4px;max-height:220px;overflow-y:auto;' });
        const log = el('pre', { id: id('log'), style: 'display:none;max-height:200px;overflow:auto;background:#0b1220;padding:8px;border-radius:6px;font-size:11px;white-space:pre-wrap;' });
        const intro = sync
            ? 'Merges main back into develop in each selected repo and pushes develop. Run it after a release so develop contains the release merge commits. Branches are never deleted. Dirty repos or conflicts block the whole run before anything changes.'
            : 'Merges develop into main in each selected repo, pushes main, creates and pushes the tags, and optionally creates GitHub releases. Branches are never deleted. Repos with uncommitted changes, conflicts or unpushed develop commits block the whole run before anything changes.';
        const kids = [el('div', { style: 'font-size:11px;color:#94a3b8;border-left:3px solid #3b82f6;padding:8px 10px;background:rgba(59,130,246,0.08);', textContent: intro }), status, list];
        if (!sync) {
            kids.push(
                field('tags', 'Tags (one per line). Apps get only their own tag (gyo-v… → gyo); packages get all. Preview shows who gets what.',
                    el('textarea', { id: id('tags'), rows: 2, className: 'ui-input', placeholder: 'gyo-v1.2.2+247\ngyo-business-v1.0.7+164' })),
                field('notes', 'Release notes', el('textarea', { id: id('notes'), rows: 5, className: 'ui-input', placeholder: 'Release notes (tag message and GitHub release body for each app)' })),
                field('pkg', 'GitHub release note for repos with no tag of their own ({tags} = tag list)', el('input', { id: id('pkg'), type: 'text', className: 'ui-input', value: 'Release for {tags}.' })),
                el('label', { style: 'display:flex;gap:8px;align-items:center;font-size:12px;' }, [el('input', { id: id('gh'), type: 'checkbox', checked: true }), 'Create GitHub releases (needs gh CLI logged in)']),
                el('label', { style: 'display:flex;gap:8px;align-items:center;font-size:12px;' }, [el('input', { id: id('back'), type: 'checkbox', checked: true }), 'After release, merge main back into develop'])
            );
        }
        kids.push(log);

        const previewBtn = btn('1. Preview', 'secondary');
        const runBtn = btn(sync ? '2. Sync selected' : '2. Release selected', 'primary', { disabled: true });
        const closeBtn = btn('Close', 'outline');
        const dialog = el('div', { className: 'ui-modal' }, [
            el('div', { className: 'ui-modal-header' }, [el('h3', { className: 'ui-modal-title', textContent: sync ? '🔁 Sync develop with main' : '🚀 Release All Repos (develop → main)' })]),
            el('div', { className: 'ui-modal-body', style: 'display:flex;flex-direction:column;gap:12px;' }, kids),
            el('div', { className: 'ui-modal-footer' }, [closeBtn, previewBtn, runBtn])
        ]);
        dialog.dataset.size = 'lg';
        const modal = el('div', { className: 'modal hidden', id: id('modal') }, [dialog]);
        document.body.append(modal);

        const tagList = () => (g('tags') ? g('tags').value.split('\n').map(t => t.trim()).filter(Boolean) : []);
        const branches = sync ? { sourceBranch: 'main', releaseBranch: 'develop' } : {};

        previewBtn.addEventListener('click', async () => {
            status.textContent = 'Fetching all repos...';
            list.replaceChildren();
            state.rows = [];
            runBtn.disabled = true;
            try {
                const data = await post('/api/git/release/all/preview', { ...branches, tags: tagList() });
                if (!data.success) { status.textContent = '❌ ' + data.error; return; }
                data.repos.forEach(plan => {
                    const box = el('input', { type: 'checkbox', checked: plan.ok && (!sync || plan.strategy !== 'up-to-date'), disabled: !plan.ok });
                    const detail = plan.ok
                        ? ` (${sync ? 'develop' : 'main'} behind ${plan.behind}, ${sync ? 'main' : 'develop'} ahead ${plan.ahead})` + (sync ? '' : ` → tags: ${(plan.tags || []).join(', ') || 'none'}`)
                        : ` ⛔ ${plan.reason || ''}`;
                    list.append(el('label', { style: 'display:flex;gap:8px;align-items:center;font-size:12px;' + (plan.ok ? '' : 'opacity:.6;') }, [box, `${plan.repoName} — ${plan.strategy}${detail}`]));
                    state.rows.push({ plan, box });
                });
                const blocked = data.repos.filter(p => !p.ok).length;
                status.textContent = `${data.repos.length} repos checked, ${blocked} not eligible (greyed out).`;
                runBtn.disabled = false;
            } catch (e) {
                status.textContent = '❌ Network error: ' + e.message;
            }
        });

        runBtn.addEventListener('click', async () => {
            const repoPaths = state.rows.filter(r => r.box.checked && !r.box.disabled).map(r => r.plan.repoPath);
            if (!repoPaths.length) { alert('Select at least one repo.'); return; }
            let payload;
            if (sync) {
                if (!confirm(`Merge main into develop and push develop in ${repoPaths.length} repo(s)?`)) return;
                payload = { ...branches, mode: 'sync', repoPaths };
            } else {
                const tags = tagList();
                if (!tags.length && !confirm('No tags entered. Merge only, without tagging?')) return;
                if (!confirm(`Merge develop into main and push in ${repoPaths.length} repo(s)?\nTags: ${tags.join(', ') || '(none)'}\n\nThis pushes to origin/main.`)) return;
                payload = {
                    repoPaths, tags,
                    notes: g('notes').value,
                    packageNote: g('pkg').value,
                    githubReleases: g('gh').checked,
                    backMerge: g('back').checked
                };
            }
            runBtn.disabled = true;
            log.style.display = 'block';
            log.textContent = 'Starting...\n';
            const data = await post('/api/git/release/all/run', payload);
            if (!data.success) { log.textContent = '❌ ' + data.error; runBtn.disabled = false; return; }
            clearInterval(pollTimer);
            pollTimer = setInterval(async () => {
                try {
                    const res = await fetch(apiUrl(`/api/job?id=${encodeURIComponent(data.jobId)}`));
                    const j = await res.json();
                    if (!j.success) return;
                    log.textContent = j.job.output + (j.job.error ? '\n❌ ' + j.job.error : '');
                    log.scrollTop = log.scrollHeight;
                    if (j.job.status === 'success' || j.job.status === 'error') {
                        clearInterval(pollTimer);
                        runBtn.disabled = false;
                        if (j.job.status === 'success' && window.showGitflowToast) showGitflowToast(sync ? 'Sync complete' : 'Release complete', 'All selected repos done.');
                    }
                } catch (_) { /* keep polling */ }
            }, 1500);
        });
        closeBtn.addEventListener('click', () => { clearInterval(pollTimer); modal.classList.add('hidden'); });
        return modal;
    }

    const open = (mode) => () => {
        if (!modals[mode]) modals[mode] = build(mode);
        modals[mode].classList.remove('hidden');
    };
    window.openReleaseAllModal = open('release');
    window.openSyncDevelopModal = open('sync');
})();
