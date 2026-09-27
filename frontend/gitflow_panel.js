// ==========================================
// Gitflow Developer Console Implementation
// ==========================================
let _selectedGitflowRepo = null;
const _gitflowStateByRepo = new Map();
let _gitflowBaseBranchPicker = null;
let _gitflowBaseBranchNames = [];

function initGitflowRepoState(repoPath) {
    if (_gitflowStateByRepo.has(repoPath)) return _gitflowStateByRepo.get(repoPath);

    const defaultState = {
        activeBranchesCount: 0,
        productionVersion: "v1.0.0",
        ciCdHealth: 94,
        selectedReleaseIndex: 0,
        qaSignoff: true,
        branches: [],
        releaseLogs: [],
        isLoading: true
    };

    _gitflowStateByRepo.set(repoPath, defaultState);
    return defaultState;
}

window.selectGitflowRepo = async function selectGitflowRepo(repoPath, cardElement) {
    _selectedGitflowRepo = repoPath;
    
    // Manage visual card selection (support both legacy .git-repo and new .gs1-card)
    document.querySelectorAll('.git-repo, .gs1-card').forEach(c => c.classList.remove('selected'));
    if (cardElement) {
        cardElement.classList.add('selected');
    } else {
        const card = document.querySelector(`.git-repo[data-repo-path-enc="${encodeURIComponent(repoPath)}"], .gs1-card[data-repo-path-enc="${encodeURIComponent(repoPath)}"]`);
        if (card) card.classList.add('selected');
    }

    // Sync dropdown with selection
    const termSelect = document.getElementById('gitTerminalRepoSelect');
    if (termSelect && termSelect.value !== repoPath) {
        termSelect.value = repoPath;
        if (typeof updateTerminalPrompt === 'function') {
            updateTerminalPrompt();
        }
    }

    // Show console
    const section = document.getElementById('gitflowDashboardSection');
    const label = document.getElementById('gitflowActiveRepoLabel');
    if (section) section.classList.remove('hidden');
    if (label) label.textContent = PathBasename(repoPath);

    const state = initGitflowRepoState(repoPath);
    state.isLoading = true;
    renderGitflowConsole(repoPath);

    try {
        const url = apiUrl('/api/git/branches?repoPath=' + encodeURIComponent(repoPath));
        const res = await fetch(url);
        const data = await res.json();
        
        if (data && data.success) {
            state.isLoading = false;
            // Process branches
            const realBranches = (data.branchStatuses || []).map(b => {
                const name = b.name;
                let type = 'FEATURE';
                const nameLower = name.toLowerCase();
                if (nameLower === 'main' || nameLower === 'master') {
                    type = 'MAIN';
                } else if (nameLower === 'develop' || nameLower === 'dev') {
                    type = 'DEVELOP';
                } else if (nameLower.startsWith('feature/') || nameLower.startsWith('features/') || nameLower.startsWith('feat/')) {
                    type = 'FEATURE';
                } else if (nameLower.startsWith('release/') || nameLower.startsWith('releases/')) {
                    type = 'RELEASE';
                } else if (nameLower.startsWith('hotfix/') || nameLower.startsWith('hotfixes/')) {
                    type = 'HOTFIX';
                } else if (nameLower.startsWith('bugfix/') || nameLower.startsWith('bugfixes/') || nameLower.startsWith('fix/')) {
                    type = 'BUGFIX';
                } else if (nameLower.startsWith('docs/')) {
                    type = 'DOCS';
                } else if (nameLower.startsWith('refactor/')) {
                    type = 'REFACTOR';
                } else if (nameLower.startsWith('chore/')) {
                    type = 'CHORE';
                } else if (nameLower.startsWith('test/') || nameLower.startsWith('tests/')) {
                    type = 'TEST';
                }
                
                let baseBranch = 'develop';
                if (type === 'MAIN') {
                    baseBranch = 'none';
                } else if (type === 'DEVELOP') {
                    baseBranch = 'main';
                } else if (type === 'HOTFIX') {
                    baseBranch = 'main';
                }

                let qaSignal = 'Passed';
                if (type === 'RELEASE' && b.behind > 0) {
                    qaSignal = 'Failed';
                } else if (b.ahead > 0) {
                    const sum = name.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                    qaSignal = sum % 3 === 0 ? 'Failed' : 'Passed';
                }

                return {
                    name: name,
                    type: type,
                    baseBranch: baseBranch,
                    commitsAhead: b.ahead || 0,
                    commitsBehind: b.behind || 0,
                    isMerged: b.isMerged || false,
                    qaSignal: qaSignal
                };
            });

            // Ensure MAIN and DEVELOP are present
            const hasMain = realBranches.some(b => b.type === 'MAIN');
            const hasDevelop = realBranches.some(b => b.type === 'DEVELOP');
            if (!hasMain) {
                realBranches.unshift({ name: "main", type: "MAIN", baseBranch: "none", commitsAhead: 0, commitsBehind: 0, isMerged: true, qaSignal: "Passed" });
            }
            if (!hasDevelop) {
                realBranches.splice(hasMain ? 1 : 0, 0, { name: "develop", type: "DEVELOP", baseBranch: "main", commitsAhead: 0, commitsBehind: 0, isMerged: false, qaSignal: "Passed" });
            }

            state.branches = realBranches;
            state.activeBranchesCount = realBranches.length;

            // Process latest tag (Production Version)
            if (data.latestTag) {
                state.productionVersion = data.latestTag;
            } else {
                state.productionVersion = "v1.0.0";
            }

            // Process release logs (Changelog History)
            if (Array.isArray(data.releaseLogs) && data.releaseLogs.length > 0) {
                state.releaseLogs = data.releaseLogs;
            } else {
                state.releaseLogs = [
                    {
                        version: "v1.0.0",
                        date: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
                        changelog: "✨ **New Features**\n* Initial repository initialization\n\n🐛 **Bug Fixes**\n* Base project configurations setups"
                    }
                ];
            }

            renderGitflowConsole(repoPath);
        }
    } catch (err) {
        console.error("Failed to load real branches dynamic data:", err);
        state.isLoading = false;
        const container = document.getElementById('gitflowConsole');
        if (container) {
            container.innerHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; gap: 16px; background: rgba(11, 14, 32, 0.4); border: 1px solid #151d3f; border-radius: 10px; padding: 24px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.4);">
                    <div style="font-size: 32px;">⚠️</div>
                    <div style="color: #ff8a8a; font-weight: 600; font-size: 14px;">Failed to Load Repository History</div>
                    <div style="color: #a0aec0; font-size: 12px; max-width: 400px; word-break: break-all;">${err.message}</div>
                    <button class="api-btn primary small" style="margin-top: 10px;" onclick="selectGitflowRepo(decodeURIComponent('${encodeURIComponent(repoPath)}'))">Retry Connection</button>
                </div>
            `;
        }
    }
}

function renderGitflowConsole(repoPath) {
    const container = document.getElementById('gitflowConsole');
    if (!container) return;

    const state = _gitflowStateByRepo.get(repoPath);
    if (!state) return;

    if (state.isLoading) {
        container.innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; gap: 16px; background: rgba(11, 14, 32, 0.4); border: 1px solid #151d3f; border-radius: 10px; padding: 24px; text-align: center; box-shadow: inset 0 0 20px rgba(0,0,0,0.5);">
                <div class="gitflow-spinner"></div>
                <div style="color: #8ab4ff; font-weight: 600; font-size: 13px; letter-spacing: 0.5px; animation: pulse 2s infinite;">Loading repository git history...</div>
            </div>
        `;
        return;
    }

    const totalCount = state.branches.length;
    const mainCount = state.branches.filter(b => b.type === 'MAIN').length;
    const featCount = state.branches.filter(b => b.type === 'FEATURE').length;
    const relCount = state.branches.filter(b => b.type === 'RELEASE').length;
    const hotCount = state.branches.filter(b => b.type === 'HOTFIX').length;

    container.innerHTML = `
        <div class="gitflow-metrics-row">
            <div class="gitflow-metric-card" style="padding: 16px 20px;">
                <div class="gitflow-metric-content">
                    <span class="gitflow-metric-title">Active Branches</span>
                    <span class="gitflow-metric-value">${totalCount}</span>
                    <span class="gitflow-metric-subtitle">${mainCount} Main, ${relCount} Release, ${featCount} Feature</span>
                </div>
            </div>
            <div class="gitflow-metric-card" style="padding: 16px 20px;">
                <div class="gitflow-metric-content">
                    <span class="gitflow-metric-title">Production Status</span>
                    <span class="gitflow-metric-value">${state.productionVersion}</span>
                    <span class="gitflow-metric-subtitle">${hotCount} Hotfixes this month</span>
                </div>
            </div>
        </div>
    `;
}

window.toggleGitflowGuide = () => {
    const panel = document.getElementById('gitflowGuidePanel');
    const btn = document.getElementById('gitflowGuideToggleBtn');
    if (!panel) return;
    if (panel.classList.contains('hidden')) {
        panel.classList.remove('hidden');
        if (btn) btn.textContent = "📖 Hide Guide";
    } else {
        panel.classList.add('hidden');
        if (btn) btn.textContent = "📖 Gitflow Guide";
    }
};

window.setGitflowHistoryIndex = (idx) => {
    if (!_selectedGitflowRepo) return;
    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    if (state) {
        state.selectedReleaseIndex = idx;
        renderGitflowConsole(_selectedGitflowRepo);
    }
};

window.triggerGitflowAction = (message) => {
    console.log(`[Gitflow Dashboard] Action triggered: ${message}`);
    showGitflowToast("Action Triggered", message);
};

window.deleteGitflowBranch = (idx) => {
    if (!_selectedGitflowRepo) return;
    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    if (state && state.branches[idx]) {
        const name = state.branches[idx].name;
        state.branches.splice(idx, 1);
        state.activeBranchesCount = state.branches.length;
        showGitflowToast("Branch Deleted", `Successfully deleted branch "${name}"`);
        renderGitflowConsole(_selectedGitflowRepo);
    }
};

window.initiateReleaseGitflow = () => {
    if (!_selectedGitflowRepo) return;
    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    if (!state) return;

    // Check if release already exists
    if (state.branches.some(b => b.type === 'RELEASE')) {
        alert("⚠️ Active release branch already exists! Finalize the current release before starting a new one.");
        return;
    }

    const nextVer = "release/v1.1.5";
    state.branches.push({
        name: nextVer,
        type: "RELEASE",
        baseBranch: "develop",
        commitsAhead: 0,
        commitsBehind: 0,
        isMerged: false,
        qaSignal: "Failed" // default fails until QA signoff
    });

    state.activeBranchesCount = state.branches.length;
    showGitflowToast("Release Initiated", `Created release branch "${nextVer}" locked to DEVELOP.`);
    renderGitflowConsole(_selectedGitflowRepo);
};

window.finalizeGitflowRelease = () => {
    if (!_selectedGitflowRepo) return;
    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    if (!state) return;

    const relIdx = state.branches.findIndex(b => b.type === 'RELEASE');
    if (relIdx === -1) return;

    const relBranch = state.branches[relIdx];

    // Simulate QA Signoff validation
    if (relBranch.qaSignal !== 'Passed') {
        const approve = confirm("⚠️ QA Signal is currently FAILED. Do you want to sign off QA testing and finalize release?");
        if (!approve) return;
        relBranch.qaSignal = 'Passed';
        showGitflowToast("QA Signoff Updated", "QA Testing verification passed.");
    }

    // Merge release into main & develop, add new changelog
    state.productionVersion = "v1.1.5";
    state.releaseLogs.unshift({
        version: "v1.1.5",
        date: new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
        changelog: `✨ **New Features**\n* Finalized release 1.1.5 production build\n* Merged release branch back to main and develop`
    });

    // Remove release branch
    state.branches.splice(relIdx, 1);
    state.activeBranchesCount = state.branches.length;

    showGitflowToast("Release Finalized", "Successfully merged v1.1.5 to MAIN and DEVELOP. Published tag v1.1.5.");
    renderGitflowConsole(_selectedGitflowRepo);
};

window.openGitflowBranchModal = (type = 'feature', branchName = '') => {
    const modal = document.getElementById('gitflowNewBranchModal');
    if (!modal) return;

    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    const branches = state ? state.branches : [];

    // Build the base-branch picker's options list, `develop`/`main` first.
    let branchNames = branches.map(b => b.name);
    if (branchNames.length === 0) branchNames = ['develop'];
    const basePriority = ['develop', 'main', 'master', 'production', 'release'];
    branchNames.sort((x, y) => {
        const idxX = basePriority.indexOf(x);
        const idxY = basePriority.indexOf(y);
        if (idxX !== -1 && idxY !== -1) return idxX - idxY;
        if (idxX !== -1) return -1;
        if (idxY !== -1) return 1;
        return x.localeCompare(y);
    });
    _gitflowBaseBranchNames = branchNames;

    const baseBranchField = document.getElementById('gitflowBaseBranchField');
    if (_gitflowBaseBranchPicker) _gitflowBaseBranchPicker.destroy();
    if (baseBranchField && typeof _createGitBranchPicker === 'function') {
        _gitflowBaseBranchPicker = _createGitBranchPicker({
            container: baseBranchField,
            branches: branchNames,
            initialValue: branchNames.includes('develop') ? 'develop' : branchNames[0],
            onSelect: () => updateGitflowModalOutputs(false),
        });
    }

    // Reset inputs
    document.getElementById('gitflowBranchType').value = type.toLowerCase();
    document.getElementById('gitflowTicketName').value = branchName ? branchName.split('/').pop() + "-split" : "referral-program";
    
    // Automatically suggest version namespace prefixed by clean repository name ONLY for packages (not apps)
    const repoDir = _selectedGitflowRepo ? _selectedGitflowRepo.split('/').pop() : '';
    const cleanRepoName = repoDir.toLowerCase().replace(/_/g, '-');
    const isApp = _selectedGitflowRepo && _selectedGitflowRepo.includes('/apps/');
    const defaultScope = (isApp || !cleanRepoName) ? 'v1.1.3' : `${cleanRepoName}-v1.1.3`;
    document.getElementById('gitflowVersionScope').value = defaultScope;

    updateGitflowModalOutputs(true);
    modal.classList.remove('hidden');
};

window.closeGitflowBranchModal = () => {
    const modal = document.getElementById('gitflowNewBranchModal');
    if (modal) modal.classList.add('hidden');
    if (_gitflowBaseBranchPicker) { _gitflowBaseBranchPicker.destroy(); _gitflowBaseBranchPicker = null; }
};

window.openGitflowTagModal = () => {
    const modal = document.getElementById('gitflowNewTagModal');
    if (!modal) return;
    document.getElementById('gitflowTagNameInput').value = '';
    document.getElementById('gitflowTagMessageInput').value = '';
    const pushRemoteCb = document.getElementById('gitflowTagPushRemote');
    if (pushRemoteCb) pushRemoteCb.checked = false;
    const tagMelosCb = document.getElementById('gitflowTagUseMelos');
    const globalMelos = document.getElementById('gitGlobalUseMelos');
    if (tagMelosCb && globalMelos) {
        tagMelosCb.checked = globalMelos.checked;
    }
    updateGitflowTagModalPreview();
    modal.classList.remove('hidden');
};

function updateGitflowTagModalPreview() {
    const repoName = _selectedGitflowRepo ? (_selectedGitflowRepo.split('/').pop() || 'app') : 'app';
    const slug = repoName.replace(/_/g, '-');
    const inputVal = document.getElementById('gitflowTagNameInput')?.value.trim() || '';
    const tagVer = inputVal ? (inputVal.startsWith('v') ? inputVal : 'v' + inputVal) : 'v1.0.4+89';
    const tagMelosCb = document.getElementById('gitflowTagUseMelos');
    const useMelos = tagMelosCb ? tagMelosCb.checked : true;
    const noteEl = document.getElementById('gitflowTagInfoNote');
    if (!noteEl) return;

    if (useMelos) {
        noteEl.innerHTML = `💡 <strong>Release Tag Convention (Melos):</strong> App repository (<code>${repoName}</code>) will be tagged as <code>${tagVer}</code>. All package dependencies in scope will be tagged as <code>${slug}-${tagVer}</code>. Repos with existing tags will be skipped.`;
    } else {
        noteEl.innerHTML = `💡 <strong>Single Repository Mode:</strong> Tag <code>${tagVer}</code> will be created for repository <code>${repoName}</code> ONLY. Package dependencies will NOT be tagged.`;
    }
}

window.closeGitflowTagModal = () => {
    const modal = document.getElementById('gitflowNewTagModal');
    if (modal) modal.classList.add('hidden');
};

function getMelosAppTarget(repoPath) {
    if (!repoPath) return null;
    const norm = repoPath.replace(/\\/g, '/').toLowerCase();
    const match = norm.match(/\/apps\/([^\/]+)/);
    if (match) {
        const app = match[1];
        const appKebab = app.replace(/_/g, '-');
        return { make: `git-${appKebab}`, melos: `git:${app}` };
    }
    if (!norm.includes('/apps/') && !norm.includes('/packages/')) {
        return { make: 'git-all', melos: 'git:all' };
    }
    return null;
}

// Modal input updates logic
function updateGitflowModalOutputs(forceAutoSelect = false) {
    const type = document.getElementById('gitflowBranchType').value;
    const customTypeEl = document.getElementById('gitflowBranchTypeCustom');
    const versionScope = document.getElementById('gitflowVersionScope').value.trim();
    const ticketName = document.getElementById('gitflowTicketName').value.trim();
    const targetBranchEl = document.getElementById('gitflowTargetBranchName');
    const commandPreviewEl = document.getElementById('gitflowCommandPreview');

    // Auto-select standard base branch if forced or on type change
    if (forceAutoSelect === true || (forceAutoSelect instanceof Event && forceAutoSelect.target && forceAutoSelect.target.id === 'gitflowBranchType')) {
        let defaultBase = _gitflowBaseBranchNames.includes('develop') ? 'develop' : 'main';
        if (type === 'hotfix') {
            defaultBase = _gitflowBaseBranchNames.includes('main') ? 'main' : _gitflowBaseBranchNames[0];
        }
        if (_gitflowBaseBranchPicker && _gitflowBaseBranchNames.includes(defaultBase)) {
            _gitflowBaseBranchPicker.setValue(defaultBase);
        }
    }

    const base = _gitflowBaseBranchPicker ? _gitflowBaseBranchPicker.getValue() : 'develop';

    if (customTypeEl) {
        if (type === 'custom') {
            customTypeEl.classList.remove('hidden');
        } else {
            customTypeEl.classList.add('hidden');
        }
    }

    // Target branch name prefix configuration:
    // feat, feature, fix, bugfix, hotfix, release, docs, refactor, chore, test
    let prefix = type;
    if (type === 'feature') prefix = 'feature';
    else if (type === 'release') prefix = 'release';
    else if (type === 'custom') {
        prefix = customTypeEl ? (customTypeEl.value.trim() || 'custom') : 'custom';
    }

    const scopePart = versionScope ? `${versionScope}/` : '';
    const targetName = `${prefix}/${scopePart}${ticketName || 'task'}`;
    targetBranchEl.value = targetName;

    // Command live preview
    const checkoutCb = document.getElementById('gitflowCheckoutNewBranch');
    const wantsCheckout = checkoutCb ? checkoutCb.checked : true;
    
    const useMelosCb = document.getElementById('gitflowUseMelos');
    const useMelosContainer = document.getElementById('gitflowUseMelosContainer');
    const melosTarget = getMelosAppTarget(_selectedGitflowRepo);

    let useMelos = false;
    if (melosTarget) {
        if (useMelosContainer) useMelosContainer.style.display = 'flex';
        useMelos = useMelosCb ? useMelosCb.checked : false;
    } else {
        if (useMelosContainer) useMelosContainer.style.display = 'none';
    }

    // Toggle Melos notice and previews
    const melosNotice = document.getElementById('gitflowMelosNotice');
    const melosAppBranchEl = document.getElementById('gitflowMelosAppBranch');
    const melosPkgBranchEl = document.getElementById('gitflowMelosPkgBranch');

    const repoDir = _selectedGitflowRepo ? _selectedGitflowRepo.split('/').pop() : '';
    const cleanRepo = repoDir.toLowerCase().replace(/_/g, '-');
    const isApp = _selectedGitflowRepo && _selectedGitflowRepo.includes('/apps/');

    // Strip prefix for app repository
    let appVersionScope = versionScope;
    if (versionScope.startsWith(cleanRepo + '/')) {
        appVersionScope = versionScope.substring(cleanRepo.length + 1);
    } else if (versionScope.startsWith(cleanRepo + '-')) {
        appVersionScope = versionScope.substring(cleanRepo.length + 1);
    }
    const appBranch = `${prefix}/${appVersionScope}/${ticketName || 'ticket'}`;

    // Format nested namespace for packages: cleanRepo/versionScope (using slash / instead of dash -)
    let pkgVersionScope = versionScope;
    if (versionScope.startsWith(cleanRepo + '-')) {
        pkgVersionScope = cleanRepo + '/' + versionScope.substring(cleanRepo.length + 1);
    } else if (!versionScope.startsWith(cleanRepo + '/')) {
        pkgVersionScope = cleanRepo ? `${cleanRepo}/${versionScope}` : versionScope;
    }
    const pkgBranch = `${prefix}/${pkgVersionScope}/${ticketName || 'ticket'}`;

    if (useMelos && melosTarget && isApp) {
        if (melosNotice) melosNotice.style.display = 'block';
        if (melosAppBranchEl) melosAppBranchEl.textContent = appBranch;
        if (melosPkgBranchEl) melosPkgBranchEl.textContent = pkgBranch;
    } else {
        if (melosNotice) melosNotice.style.display = 'none';
    }
    
    if (useMelos && melosTarget) {
        const cmdBranchName = isApp ? appBranch : (isApp ? targetName : `${prefix}/${pkgVersionScope}/${ticketName || 'ticket'}`);
        if (wantsCheckout) {
            commandPreviewEl.textContent = `make ${melosTarget.make} CMD="checkout -b ${cmdBranchName} ${base}"`;
        } else {
            commandPreviewEl.textContent = `make ${melosTarget.make} CMD="branch ${cmdBranchName} ${base}"`;
        }
    } else {
        if (wantsCheckout) {
            commandPreviewEl.textContent = `git checkout -b ${targetName} ${base}`;
        } else {
            commandPreviewEl.textContent = `git branch ${targetName} ${base}`;
        }
    }
}

function showGitflowToast(title, body, type = 'success') {
    const container = document.getElementById('gitflowToastContainer');
    if (!container) return;

    const icon = type === 'error' ? '⚠️' : '✅';
    const toast = document.createElement('div');
    toast.className = 'gitflow-toast';
    toast.innerHTML = `
        <div style="font-size:18px;">${icon}</div>
        <div>
            <div style="font-weight: 700; margin-bottom: 2px;">${title}</div>
            <div style="font-size: 11px; color: #a0aec0;">${body}</div>
        </div>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Safe setup loader for modal event listeners
function initGitflowModalListeners() {
    const closeBtn = document.getElementById('gitflowNewBranchClose');
    const cancelBtn = document.getElementById('gitflowNewBranchCancel');
    const submitBtn = document.getElementById('gitflowNewBranchSubmit');
    const typeSelect = document.getElementById('gitflowBranchType');
    const customTypeEl = document.getElementById('gitflowBranchTypeCustom');
    const scopeInput = document.getElementById('gitflowVersionScope');
    const nameInput = document.getElementById('gitflowTicketName');
    const checkoutCb = document.getElementById('gitflowCheckoutNewBranch');

    if (closeBtn) closeBtn.addEventListener('click', closeGitflowBranchModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeGitflowBranchModal);
    if (typeSelect) typeSelect.addEventListener('change', updateGitflowModalOutputs);
    if (customTypeEl) customTypeEl.addEventListener('input', () => updateGitflowModalOutputs(false));
    // Base branch changes are wired per-open via _createGitBranchPicker's onSelect (see openGitflowBranchModal).
    if (scopeInput) scopeInput.addEventListener('input', () => updateGitflowModalOutputs(false));
    if (nameInput) nameInput.addEventListener('input', () => updateGitflowModalOutputs(false));
    if (checkoutCb) checkoutCb.addEventListener('change', () => updateGitflowModalOutputs(false));

    const globalMelos = document.getElementById('gitGlobalUseMelos');
    const modalMelos = document.getElementById('gitflowUseMelos');
    if (globalMelos && modalMelos) {
        globalMelos.addEventListener('change', () => {
            modalMelos.checked = globalMelos.checked;
            updateGitflowModalOutputs(false);
        });
        modalMelos.addEventListener('change', () => {
            globalMelos.checked = modalMelos.checked;
            updateGitflowModalOutputs(false);
        });
    }
    if (modalMelos) {
        modalMelos.addEventListener('change', () => updateGitflowModalOutputs(false));
    }

    const tagInput = document.getElementById('gitflowTagNameInput');
    const tagMelosCb = document.getElementById('gitflowTagUseMelos');
    if (tagInput) tagInput.addEventListener('input', updateGitflowTagModalPreview);
    if (tagMelosCb) tagMelosCb.addEventListener('change', updateGitflowTagModalPreview);

    if (submitBtn) {
        submitBtn.addEventListener('click', () => {
            if (!_selectedGitflowRepo) return;
            const base = _gitflowBaseBranchPicker ? _gitflowBaseBranchPicker.getValue() : 'develop';
            const name = document.getElementById('gitflowTargetBranchName').value.trim();
            const wantsCheckout = checkoutCb ? checkoutCb.checked : true;

            if (!name) {
                alert("❌ Branch name is empty");
                return;
            }

            const useMelosCb = document.getElementById('gitflowUseMelos');
            const useMelos = useMelosCb ? useMelosCb.checked : false;

            const makeCall = (skipExisting = false) => {
                submitBtn.disabled = true;
                submitBtn.textContent = skipExisting ? "Creating in packages..." : "Creating & pushing...";

                fetch(apiUrl('/api/git/branch/create'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        repoPath: _selectedGitflowRepo,
                        branchName: name,
                        baseBranch: base,
                        checkout: wantsCheckout,
                        useMelos: useMelos,
                        skipExisting: skipExisting,
                        githubToken: localStorage.getItem('devgit_github_token_v1') || ''
                    })
                })
                .then(res => res.json())
                .then(data => {
                    submitBtn.disabled = false;
                    submitBtn.textContent = "Create Branch";

                    if (data.alreadyExists) {
                        if (data.missingRepos && data.missingRepos.length > 0) {
                            const msg = `⚠️ Branch already exists in: ${data.existingRepos.join(', ')}.\n\nIt is missing in: ${data.missingRepos.join(', ')}.\n\nWould you like to create the branch only in the missing package repositories?`;
                            if (confirm(msg)) {
                                makeCall(true); // Re-fire with skipExisting = true
                            }
                        } else {
                            alert(`❌ Branch already exists on all repositories in scope:\n\n${data.existingRepos.join(', ')}`);
                        }
                        return;
                    }

                    if (!data.success) {
                        if (window.handleGitflowError) {
                            window.handleGitflowError("Failed to create branch", data.error || 'Unknown error');
                        } else {
                            alert("❌ Failed to create branch: " + (data.error || 'Unknown error'));
                        }
                        return;
                    }
                    
                    const toastMsg = wantsCheckout ? `Successfully created and checked out ${name}` : `Successfully created branch ${name}`;
                    showGitflowToast("Branch created", toastMsg);
                    closeGitflowBranchModal();
                    selectGitflowRepo(_selectedGitflowRepo);

                    // Silently refresh Screen 2 to show the newly created branch instantly
                    if (typeof openRepoDetailScreen === 'function') {
                        if (window._gitBranchStatusCache) {
                            window._gitBranchStatusCache.delete(_selectedGitflowRepo);
                        }
                        openRepoDetailScreen(_selectedGitflowRepo, true);
                    }
                    // Silently refresh Screen 1 cards (so branch count updates)
                    if (typeof loadGitRepos === 'function') {
                        loadGitRepos(true);
                    }
                })
                .catch(err => {
                    submitBtn.disabled = false;
                    submitBtn.textContent = "Create Branch";
                    alert("❌ Network Error: " + err.message);
                });
            };

            makeCall(false);
        });
    }

    const tagCloseBtn = document.getElementById('gitflowNewTagClose');
    const tagCancelBtn = document.getElementById('gitflowNewTagCancel');
    const tagSubmitBtn = document.getElementById('gitflowNewTagSubmit');

    if (tagCloseBtn) tagCloseBtn.addEventListener('click', closeGitflowTagModal);
    if (tagCancelBtn) tagCancelBtn.addEventListener('click', closeGitflowTagModal);
    if (tagSubmitBtn) {
        tagSubmitBtn.addEventListener('click', () => {
            if (!_selectedGitflowRepo) return;
            const tagName = document.getElementById('gitflowTagNameInput').value.trim();
            const message = document.getElementById('gitflowTagMessageInput').value.trim();
            const pushToRemote = !!document.getElementById('gitflowTagPushRemote')?.checked;

            if (!message) {
                alert("Please provide a Release Message / Changelog!");
                return;
            }

            tagSubmitBtn.disabled = true;
            tagSubmitBtn.textContent = "Creating Tags...";

            const tagMelosCb = document.getElementById('gitflowTagUseMelos');
            const globalMelos = document.getElementById('gitGlobalUseMelos');
            const useMelos = tagMelosCb ? tagMelosCb.checked : (globalMelos ? globalMelos.checked : false);

            fetch(apiUrl('/api/git/tag/create'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    repoPath: _selectedGitflowRepo,
                    tagName: tagName,
                    message: message,
                    useMelos: useMelos,
                    pushToRemote: pushToRemote,
                    githubToken: localStorage.getItem('devgit_github_token_v1') || ''
                })
            })
            .then(res => res.json())
            .then(data => {
                tagSubmitBtn.disabled = false;
                tagSubmitBtn.textContent = "Create Release Tag";
                if (!data.success) {
                    if (window.handleGitflowError) {
                        window.handleGitflowError("Failed to create tag", data.error);
                    } else {
                        alert("❌ Failed to create tag: " + data.error);
                    }
                    return;
                }
                
                const statusMsg = data.pushedToRemote 
                    ? `Created & pushed tags across repos (App: ${data.appTagName || data.tagName}).`
                    : `Created tags locally across ${data.createdCount || 1} repos (App: ${data.appTagName || data.tagName}, Packages: ${data.pkgTagPrefix || ''}...).\nReady to push when reviewed.`;
                    
                showGitflowToast(data.pushedToRemote ? "Tags Published" : "Tags Created Locally", statusMsg);
                closeGitflowTagModal();
                
                // Immediately refresh repository select status to fetch newly created git tags!
                selectGitflowRepo(_selectedGitflowRepo);

                // Silently refresh Screen 2 and Screen 1
                if (typeof openRepoDetailScreen === 'function') {
                    if (window._gitBranchStatusCache) {
                        window._gitBranchStatusCache.delete(_selectedGitflowRepo);
                    }
                    openRepoDetailScreen(_selectedGitflowRepo, true);
                }
                if (typeof loadGitRepos === 'function') {
                    loadGitRepos(true);
                }
            })
            .catch(err => {
                tagSubmitBtn.disabled = false;
                tagSubmitBtn.textContent = "Create Release Tag";
                alert("❌ Network Error: " + err.message);
            });
        });
    }

window.pushGitflowTagsRemote = (repoPath) => {
    const targetRepo = repoPath || _selectedGitflowRepo;
    if (!targetRepo) return;
    const globalMelos = document.getElementById('gitGlobalUseMelos');
    const useMelos = globalMelos ? globalMelos.checked : false;

    if (!confirm("Are you sure you want to push all local release tags to remote origin?")) {
        return;
    }

    setGitStatus("Pushing local tags to remote origin...");
    fetch(apiUrl('/api/git/tag/push'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            repoPath: targetRepo,
            useMelos: useMelos,
            githubToken: localStorage.getItem('devgit_github_token_v1') || ''
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            setGitStatus("✓ " + data.message, 'success');
            showGitflowToast("Tags Pushed", data.message);
            if (typeof loadGitRepos === 'function') loadGitRepos(true);
        } else {
            setGitStatus("⚠️ Push tags failed: " + data.error, 'error');
            if (window.handleGitflowError) {
                window.handleGitflowError("Failed to push tags", data.error);
            } else {
                alert("❌ Failed to push tags to remote: " + data.error);
            }
        }
    })
    .catch(err => {
        setGitStatus("⚠️ Network error: " + err.message, 'error');
        alert("❌ Network Error: " + err.message);
    });
};
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGitflowModalListeners);
} else {
    initGitflowModalListeners();
}

// Decoupled card click handler
document.addEventListener('click', (e) => {
    const card = e.target.closest('.git-repo');
    if (!card) return;
    
    // Ignore if clicked on a button, select, input, or other interactive element
    const isInteractive = e.target.closest('button') || 
                          e.target.closest('select') || 
                          e.target.closest('input') || 
                          e.target.closest('.git-repo-header-actions') || 
                          e.target.closest('.git-repo-footer-badge') ||
                          e.target.closest('.git-behind-branches-box') ||
                          e.target.closest('.git-ai-badge') ||
                          e.target.closest('.git-ai-details');
    if (isInteractive) return;
    
    const repoPath = decodeURIComponent(card.getAttribute('data-repo-path-enc') || '');
    if (repoPath) {
        selectGitflowRepo(repoPath, card);
    }
});

// Auto-select helper on first render
function onPostRenderGitRepos(repos) {
    if (!Array.isArray(repos) || repos.length === 0) return;
    
    // Maintain selection if already set
    if (_selectedGitflowRepo) {
        const card = document.querySelector(`.git-repo[data-repo-path-enc="${encodeURIComponent(_selectedGitflowRepo)}"]`);
        if (card) {
            card.classList.add('selected');
        } else {
            _selectedGitflowRepo = null;
        }
    }
    
    // Auto-select first repository by default if none selected
    if (!_selectedGitflowRepo) {
        const firstRepo = repos.find(r => r.path);
        if (firstRepo) {
            selectGitflowRepo(firstRepo.path);
        }
    }
}

// Wrap original renderGitRepos to trigger post-render hook
if (typeof renderGitRepos === 'function') {
    const originalRenderGitRepos = renderGitRepos;
    renderGitRepos = function(repos) {
        originalRenderGitRepos(repos);
        onPostRenderGitRepos(repos);
    };
}

window.openGitflowPR = (name, base) => {
    if (!_selectedGitflowRepo) return;
    const state = _gitflowStateByRepo.get(_selectedGitflowRepo);
    if (!state || !state.githubUrl) {
        alert("❌ GitHub URL not found for this repository. Make sure remote origin is configured.");
        return;
    }
    const url = `${state.githubUrl}/compare/${encodeURIComponent(base)}...${encodeURIComponent(name)}`;
    window.open(url, '_blank');
};

window.finishGitflowBranch = async (event, name, base) => {
    if (!_selectedGitflowRepo) return;
    const confirmFinish = confirm(`Are you sure you want to finish branch "${name}"?\n\nThis will:\n1. Merge "${name}" into "${base}"\n2. Push "${base}" to GitHub\n3. Delete "${name}" locally and remotely on GitHub.`);
    if (!confirmFinish) return;

    const btn = event.target;
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Finishing...";

    try {
        const globalMelos = document.getElementById('gitGlobalUseMelos');
        const useMelos = globalMelos ? globalMelos.checked : false;

        const res = await fetch(apiUrl('/api/git/branch/finish'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _selectedGitflowRepo,
                branchName: name,
                baseBranch: base,
                useMelos: useMelos,
                githubToken: localStorage.getItem('devgit_github_token_v1') || ''
            })
        });
        const data = await res.json();
        if (!data.success) {
            if (window.handleGitflowError) {
                window.handleGitflowError("Failed to finish branch", data.error);
            } else {
                alert("❌ Failed to finish branch: " + data.error);
            }
            return;
        }
        showGitflowToast("Branch Finished", `Successfully merged and cleaned up ${name}.`);
        selectGitflowRepo(_selectedGitflowRepo); // Refresh console
    } catch (err) {
        alert("❌ Network Error: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

window.openGitflowViewTagsModal = async () => {
    const modal = document.getElementById('gitflowViewTagsModal');
    if (!modal) return;
    modal.classList.remove('hidden');

    const spinner = document.getElementById('gitflowViewTagsSpinner');
    const empty = document.getElementById('gitflowViewTagsEmpty');
    const container = document.getElementById('gitflowViewTagsContainer');
    const tbody = document.getElementById('gitflowViewTagsTableBody');

    spinner.classList.remove('hidden');
    empty.classList.add('hidden');
    container.classList.add('hidden');
    tbody.innerHTML = '';

    if (!_selectedGitflowRepo) {
        spinner.classList.add('hidden');
        empty.classList.remove('hidden');
        return;
    }

    try {
        const globalMelos = document.getElementById('gitGlobalUseMelos');
        const useMelos = globalMelos ? globalMelos.checked : false;

        const res = await fetch(apiUrl('/api/git/tags'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _selectedGitflowRepo,
                useMelos: useMelos,
                githubToken: localStorage.getItem('devgit_github_token_v1') || ''
            })
        });
        const data = await res.json();
        spinner.classList.add('hidden');

        if (!data.success) {
            if (window.handleGitflowError) {
                window.handleGitflowError("Failed to load tags", data.error || 'Unknown error');
            } else {
                alert("❌ Failed to load tags: " + (data.error || 'Unknown error'));
            }
            empty.classList.remove('hidden');
            return;
        }
        if (!data.tags || data.tags.length === 0) {
            empty.classList.remove('hidden');
            return;
        }

        container.classList.remove('hidden');
        data.tags.forEach(tag => {
            const tr = document.createElement('tr');
            
            const statusBadge = tag.pushed 
                ? '<span class="ui-badge" data-variant="success">Pushed</span>' 
                : '<span class="ui-badge" data-variant="warning">Local Only</span>';
            
            let actionsHtml = '';
            if (!tag.pushed) {
                actionsHtml += `<button class="ui-button" data-variant="outline" data-size="sm" onclick="openGitflowEditTagModal('${tag.version}', \`${tag.message.replace(/`/g, '\\`').replace(/'/g, "\\'")}\`)">Edit</button> `;
                actionsHtml += `<button class="ui-button" data-variant="success" data-size="sm" onclick="publishGitflowTag('${tag.version}')">Publish</button> `;
                actionsHtml += `<button class="ui-button" data-variant="danger" data-size="sm" onclick="deleteGitflowTag('${tag.version}')">Delete</button>`;
            } else {
                actionsHtml += `<span style="color:#64748b; font-size:11px;">Pushed to Remote</span>`;
            }

            let subReposHtml = '';
            if (data.isMelos && tag.repos && tag.repos.length > 0) {
                subReposHtml = `<div class="sub-repos-list">🏷️ Active on: ${tag.repos.map(r => `${r.repoName} (${r.tagName})`).join(', ')}</div>`;
            }

            tr.innerHTML = `
                <td style="font-weight: 700; color: #fff;">
                    ${tag.version}
                    ${subReposHtml}
                </td>
                <td style="white-space: pre-wrap; line-height: 1.4;">${tag.message}</td>
                <td>${statusBadge}</td>
                <td>${actionsHtml}</td>
            `;
            tbody.appendChild(tr);
        });

    } catch (err) {
        spinner.classList.add('hidden');
        alert("❌ Error loading tags: " + err.message);
    }
};

window.closeGitflowViewTagsModal = () => {
    const modal = document.getElementById('gitflowViewTagsModal');
    if (modal) modal.classList.add('hidden');
};

let _editingTagVersion = '';

window.openGitflowEditTagModal = (version, currentMessage) => {
    const modal = document.getElementById('gitflowEditTagModal');
    if (!modal) return;
    _editingTagVersion = version;
    document.getElementById('gitflowEditTagNameInput').value = version;
    document.getElementById('gitflowEditTagMessageInput').value = currentMessage || '';
    modal.classList.remove('hidden');
};

window.closeGitflowEditTagModal = () => {
    const modal = document.getElementById('gitflowEditTagModal');
    if (modal) modal.classList.add('hidden');
};

// Setup Modal action listeners
const viewTagsClose = document.getElementById('gitflowViewTagsClose');
const viewTagsCancel = document.getElementById('gitflowViewTagsCancel');
if (viewTagsClose) viewTagsClose.addEventListener('click', closeGitflowViewTagsModal);
if (viewTagsCancel) viewTagsCancel.addEventListener('click', closeGitflowViewTagsModal);

const editTagsClose = document.getElementById('gitflowEditTagClose');
const editTagsCancel = document.getElementById('gitflowEditTagCancel');
const editTagsSubmit = document.getElementById('gitflowEditTagSubmit');
if (editTagsClose) editTagsClose.addEventListener('click', closeGitflowEditTagModal);
if (editTagsCancel) editTagsCancel.addEventListener('click', closeGitflowEditTagModal);

if (editTagsSubmit) {
    editTagsSubmit.addEventListener('click', async () => {
        const newVersion = document.getElementById('gitflowEditTagNameInput').value.trim();
        const message = document.getElementById('gitflowEditTagMessageInput').value.trim();
        if (!newVersion || !message) {
            alert("❌ Version and Release message are required.");
            return;
        }

        editTagsSubmit.disabled = true;
        editTagsSubmit.textContent = "Saving...";

        try {
            const globalMelos = document.getElementById('gitGlobalUseMelos');
            const useMelos = globalMelos ? globalMelos.checked : false;

            const res = await fetch(apiUrl('/api/git/tag/edit'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    repoPath: _selectedGitflowRepo,
                    oldVersion: _editingTagVersion,
                    newVersion: newVersion,
                    message: message,
                    useMelos: useMelos
                })
            });
            const data = await res.json();
            if (data.success) {
                showGitflowToast("Tag Updated", `Successfully updated tag to ${newVersion}.`);
                closeGitflowEditTagModal();
                openGitflowViewTagsModal(); // Refresh view tags table
            } else {
                alert("❌ Failed to edit tag: " + data.error);
            }
        } catch (err) {
            alert("❌ Network Error: " + err.message);
        } finally {
            editTagsSubmit.disabled = false;
            editTagsSubmit.textContent = "Save Changes";
        }
    });
}

window.deleteGitflowTag = async (version) => {
    if (!confirm(`Are you sure you want to delete local tag "${version}"?`)) {
        return;
    }

    try {
        const globalMelos = document.getElementById('gitGlobalUseMelos');
        const useMelos = globalMelos ? globalMelos.checked : false;

        const res = await fetch(apiUrl('/api/git/tag/delete'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _selectedGitflowRepo,
                version: version,
                useMelos: useMelos
            })
        });
        const data = await res.json();
        if (data.success) {
            showGitflowToast("Tag Deleted", `Successfully deleted tag "${version}".`);
            openGitflowViewTagsModal(); // Refresh list
        } else {
            alert("❌ Failed to delete tag: " + data.error);
        }
    } catch (err) {
        alert("❌ Network Error: " + err.message);
    }
};

window.publishGitflowTag = async (version) => {
    if (!confirm(`Are you sure you want to publish tag "${version}" to remote origin?`)) {
        return;
    }

    try {
        const globalMelos = document.getElementById('gitGlobalUseMelos');
        const useMelos = globalMelos ? globalMelos.checked : false;

        const res = await fetch(apiUrl('/api/git/tag/push'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repoPath: _selectedGitflowRepo,
                version: version,
                useMelos: useMelos,
                githubToken: localStorage.getItem('devgit_github_token_v1') || ''
            })
        });
        const data = await res.json();
        if (data.success) {
            showGitflowToast("Tag Published", `Successfully pushed tag "${version}" to origin remote.`);
            openGitflowViewTagsModal(); // Refresh list
        } else {
            if (window.handleGitflowError) {
                window.handleGitflowError("Failed to publish tag", data.error);
            } else {
                alert("❌ Failed to publish tag: " + data.error);
            }
        }
    } catch (err) {
        alert("❌ Network Error: " + err.message);
    }
};

/* ==========================================
   Gitflow Settings Modal Actions
   ========================================== */
window.openGitflowSettingsModal = () => {
    const modal = document.getElementById('gitflowSettingsModal');
    if (!modal) return;
    const token = localStorage.getItem('devgit_github_token_v1') || '';
    const aiPrompt = localStorage.getItem('devgit_ai_prompt_template') || '';
    const tokenInput = document.getElementById('gitflowSettingsTokenInput');
    const aiPromptInput = document.getElementById('gitflowSettingsAiPromptInput');
    if (tokenInput) tokenInput.value = token;
    if (aiPromptInput) aiPromptInput.value = aiPrompt;
    modal.classList.remove('hidden');
};

window.closeGitflowSettingsModal = () => {
    const modal = document.getElementById('gitflowSettingsModal');
    if (modal) modal.classList.add('hidden');
};

// Listeners for Settings Modal
const settingsClose = document.getElementById('gitflowSettingsClose');
const settingsCancel = document.getElementById('gitflowSettingsCancel');
const settingsSubmit = document.getElementById('gitflowSettingsSubmit');
if (settingsClose) settingsClose.addEventListener('click', window.closeGitflowSettingsModal);
if (settingsCancel) settingsCancel.addEventListener('click', window.closeGitflowSettingsModal);
if (settingsSubmit) {
    settingsSubmit.addEventListener('click', () => {
        const tokenInput = document.getElementById('gitflowSettingsTokenInput');
        const aiPromptInput = document.getElementById('gitflowSettingsAiPromptInput');
        const token = tokenInput ? tokenInput.value.trim() : '';
        const aiPrompt = aiPromptInput ? aiPromptInput.value.trim() : '';
        localStorage.setItem('devgit_github_token_v1', token);
        if (aiPrompt) {
            localStorage.setItem('devgit_ai_prompt_template', aiPrompt);
        } else {
            localStorage.removeItem('devgit_ai_prompt_template');
        }
        showGitflowToast("Settings Saved", "Settings and custom AI system prompt saved.");
        window.closeGitflowSettingsModal();
    });
}

/* ==========================================
   Gitflow User-Friendly Auth Error Handling
   ========================================== */
window.handleGitflowError = (title, errorMsg) => {
    if (!errorMsg) {
        alert(`❌ ${title}: Unknown error`);
        return;
    }
    
    const isAuthError = errorMsg.includes("could not read Username") || 
                        errorMsg.includes("terminal prompts disabled") || 
                        errorMsg.includes("Device not configured") ||
                        errorMsg.includes("Permission denied");
    
    if (isAuthError) {
        const confirmGo = confirm(
            `❌ Git Authentication Failed\n\n` +
            `The background Git command could not authenticate with GitHub.\n` +
            `This happens because terminal prompts are disabled on background actions.\n\n` +
            `Would you like to open the Settings panel now to configure your GitHub Personal Access Token?`
        );
        if (confirmGo) {
            window.openGitflowSettingsModal();
        }
    } else {
        alert(`❌ ${title}: ${errorMsg}`);
    }
};
