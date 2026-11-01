// Restart / stop the DevGit server from the UI. The restarted server keeps the same workspace and token.
(function () {
    const call = async (action, force) => {
        const res = await fetch(apiUrl('/api/server/' + action), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: force === true })
        });
        return res.json();
    };

    async function waitUntilBack() {
        const deadline = Date.now() + 40000;
        await new Promise(r => setTimeout(r, 2500));
        while (Date.now() < deadline) {
            try {
                const res = await fetch(apiUrl('/api/workspace'), { cache: 'no-store' });
                if (res.ok) { location.reload(); return; }
            } catch (_) { /* still down */ }
            await new Promise(r => setTimeout(r, 1000));
        }
        alert('Server did not come back within 40s. Check /tmp/devgit-server.log or start it with ./start.sh');
    }

    async function control(action) {
        const restart = action === 'restart';
        if (!confirm(restart ? 'Restart the DevGit server? The page reloads when it is back.' : 'Stop the DevGit server? You will need to start it again from a terminal (./start.sh).')) return;
        try {
            let data = await call(action, false);
            if (!data.success && data.busy && confirm(data.error + '\n\nForce anyway? Running jobs will be killed.')) data = await call(action, true);
            if (!data.success) { if (!data.busy) alert('❌ ' + data.error); return; }
            if (restart) { document.title = 'Restarting…'; await waitUntilBack(); }
            else document.body.innerHTML = '<p style="padding:24px;font-family:sans-serif;">DevGit server stopped. Start it again with <code>./start.sh</code>.</p>';
        } catch (e) {
            alert('❌ ' + e.message);
        }
    }

    window.restartDevGitServer = () => control('restart');
    window.stopDevGitServer = () => control('stop');
})();
