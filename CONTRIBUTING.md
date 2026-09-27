# 🤝 Contributing to DevGit

Thank you for your interest in contributing to **DevGit**! DevGit is an open-source, zero-dependency Git management dashboard designed to streamline multi-repo, monorepo, and standalone Git workflows.

We welcome contributions of all kinds: bug fixes, documentation improvements, UI polish, workflow automation, and new features.

---

## 📑 Table of Contents

1. [Code of Conduct](#-code-of-conduct)
2. [Our Architectural Philosophy](#-our-architectural-philosophy)
3. [Quick Setup & Local Development](#-quick-setup--local-development)
4. [Standard Git Workflow](#-standard-git-workflow)
   - [Branch Naming Convention](#branch-naming-convention)
   - [Conventional Commits](#conventional-commits)
   - [Pull Request Lifecycle](#pull-request-lifecycle)
5. [Code Quality & Standards](#-code-quality--standards)
   - [Python (Backend)](#python-backend)
   - [JavaScript & CSS (Frontend)](#javascript--css-frontend)
6. [Submitting Issues & Feature Requests](#-submitting-issues--feature-requests)
7. [Roadmap & Good First Issues](#-roadmap--good-first-issues)

---

## 📜 Code of Conduct

DevGit follows standard open-source community standards. Please review our [.github/CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md). We expect all contributors and maintainers to treat everyone with respect, empathy, and constructive collaboration.

---

## 🏛️ Our Architectural Philosophy

DevGit is built on three core pillars:

1. **Zero External Runtime Dependencies**:
   - The backend runs on standard **Python 3.9+** without installing packages via `pip` (no Flask, no Django, no requests).
   - Only Python standard library modules (`http.server`, `subprocess`, `urllib`, `json`, `pathlib`) are used.
   - *Do not add external Python dependencies to `pyproject.toml` unless strictly necessary and discussed beforehand.*
2. **Zero Frontend Build Steps**:
   - The UI uses native HTML5, vanilla JavaScript (ES6+), and CSS.
   - No `npm`, `node_modules`, Webpack, or Vite required.
   - The central UI design system is loaded via global CDN from [`developer-dashboard-ui`](https://github.com/sunilbvb/developer-dashboard-ui) with an offline fallback.
3. **Local & Privacy First**:
   - DevGit communicates only with local Git executables and optional local Ollama instances.
   - No tracking, telemetry, or remote telemetry servers.

---

## 🚀 Quick Setup & Local Development

### Prerequisites
- **Git** (2.25+) installed and on your system `PATH`.
- **Python 3.9+** installed.
- Modern web browser (Chrome, Firefox, Safari, Edge).

### 1. Fork and Clone
```bash
# Fork the repository on GitHub, then clone your fork:
git clone https://github.com/<your-username>/dev-git.git
cd dev-git
```

### 2. Run the Development Server
```bash
# Start DevGit targeting your current workspace:
./start.sh --open

# Or specify a custom port / workspace:
./start.sh -w /path/to/test-monorepo -p 8086 --open
```

### 3. Verify in Browser
Open `http://127.0.0.1:8086` to interact with your local development build.

### 4. Run Automated Unit Tests
DevGit includes an automated unit test suite with zero external dependencies:
```bash
./scripts/run_tests.sh
# or directly with Python standard library:
python3 -m unittest discover -s tests -p "test_*.py" -v
```

---

## 🌿 Standard Git Workflow

We adhere to standard **GitHub Flow** and **Gitflow** branching conventions.

```
       feat/add-sync-button  ───●───●───●──┐
                                           │ (PR / Code Review)
main  ─────────────────●───────────────────▼───●─── (Stable Releases)
```

### Branch Naming Convention

Always create a descriptive branch for your work using standard prefixes:

| Prefix | Purpose | Example |
| :--- | :--- | :--- |
| `feat/` | New functionality or feature | `feat/git-stash-viewer` |
| `fix/` | Bug fixes or corrections | `fix/windows-path-separator` |
| `docs/` | Documentation improvements | `docs/contributing-guide` |
| `refactor/` | Code refactoring without behavioral changes | `refactor/router-dispatch` |
| `chore/` | Tooling, CI, or housekeeping updates | `chore/update-readme` |
| `test/` | Adding or updating tests | `test/melos-discovery` |

```bash
# Example: create a feature branch off main
git checkout main
git pull origin main
git checkout -b feat/my-new-feature
```

### Conventional Commits

We follow the [Conventional Commits](https://www.conventionalcommits.org/) standard. Each commit message should follow this structure:

```text
<type>(<scope>): <short description in present tense>

[optional body explaining rationale]

[optional footer(s), e.g. Fixes #123]
```

**Allowed Types:**
- `feat`: A new feature or capability.
- `fix`: A bug fix.
- `docs`: Documentation-only changes.
- `style`: Changes that do not affect code logic (formatting, missing semicolons).
- `refactor`: Code changes that neither fix a bug nor add a feature.
- `perf`: Code changes that improve performance.
- `test`: Adding missing tests or correcting existing tests.
- `chore`: Changes to build process, auxiliary tools, or libraries.

**Examples:**
```text
feat(backend): add git stash pop endpoint in router.py
fix(frontend): handle branch names with special characters in UI modal
docs: add CONTRIBUTING.md and standard git workflow guide
```

### Pull Request Lifecycle

1. **Keep PRs focused:** Submit small, targeted PRs. One feature or bugfix per PR.
2. **Sync with main:** Before submitting, ensure your branch is rebased on latest `main`:
   ```bash
   git fetch origin
   git rebase origin/main
   ```
3. **Self-Review:** Test your changes thoroughly locally. Inspect `git diff` to make sure no accidental files (`.DS_Store`, `*.pyc`, editor files) are included.
4. **Submit PR:** Push to your fork and open a Pull Request against `main`. Fill in the PR description template.

---

## 🧪 Code Quality & Standards

### Python (Backend)
- Code must be compatible with **Python 3.9+**.
- Follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines.
- Standard library only (`http.server`, `subprocess`, `urllib`, `json`, `pathlib`).
- Subprocess calls must use safe argument lists (no `shell=True` with unvalidated user input).
- Return structured JSON payloads: `{"success": true, ...}` or `{"success": false, "error": "message"}`.

### JavaScript & CSS (Frontend)
- Write modern, vanilla **ES6+ JavaScript**.
- Avoid third-party JS frameworks (no React, Vue, jQuery).
- Maintain CSS variables defined in [frontend/css/core.css](frontend/css/core.css) and [`developer-dashboard-ui`](https://github.com/sunilbvb/developer-dashboard-ui).
- Support both **dark mode** and **light mode** (respect `data-theme`).
- Keep UI resilient: graceful error banners if backend or network commands fail.

---

## 🐛 Submitting Issues & Feature Requests

### Reporting a Bug
- Check existing GitHub Issues first to avoid duplicates.
- Provide your OS version, Python version, and Git version.
- Include clear steps to reproduce the problem and terminal/browser console logs.

### Proposing a Feature
- Explain the motivation and use case for the proposed feature.
- Describe how it fits within the zero-dependency philosophy of DevGit.
- Mockups, screenshots, or sample CLI output are highly appreciated.

---

## 🎯 Roadmap & Good First Issues

Looking for somewhere to start? Here is our curated list of open tasks. If you'd like to work on one, comment on the corresponding issue or open a draft PR referencing the task title!

### 🟢 Tier 1: Good First Issue (Beginner Friendly)
*Ideal for contributors looking for a straightforward first contribution without deep architecture knowledge.*

| Task | Description | Status | Key Files |
| :--- | :--- | :---: | :--- |
| **System Theme Auto-Detect** | Detect OS theme preference via `prefers-color-scheme` media query on first visit. | ✅ Done | `frontend/index.html` |
| **Keyboard Shortcuts** | Add hotkeys: `Ctrl+K` (search), `R` (refresh), `F` (fetch), `S` (stash), `C` (copy standup), `Esc`. | ✅ Done | `frontend/app.js` |
| **Copy Status Summary** | Top-bar button and hotkey `C` to copy Markdown standup summary to clipboard. | ✅ Done | `frontend/app.js` |
| **Relative Timestamp Format** | Format commit timestamps into friendly human-readable strings ("10m ago", "Yesterday"). | ✅ Done | `frontend/app.js` |

### 🟡 Tier 2: Intermediate (Git Mechanics & Dashboard UI)
*Ideal for developers familiar with Git CLI commands, Python subprocesses, or vanilla JS components.*

| Task | Description | Status | Key Files |
| :--- | :--- | :---: | :--- |
| **Git Stash Quick-Manager** | UI modal & hotkey `S` to inspect stashes (`git stash list`) and 1-click pop/apply/drop. | ✅ Done | `backend/router.py`, `frontend/app.js` |
| **Merge Conflict Indicator** | Detect unmerged conflict states, pulse card in red, and 1-click launch Conflict Assistant. | ✅ Done | `backend/router.py`, `frontend/app.js` |
| **Real-Time Branch Filter** | Add instant text search filter in the branch popovers/switchers to filter through branches. | ✅ Done | `frontend/app.js`, `frontend/index.html` |
| **Custom AI Prompt in Settings** | Allow users to customize the system prompt template passed to Ollama for AI commits. | ✅ Done | `backend/router.py`, `frontend/gitflow_panel.js`, `frontend/app.js` |

### 🔴 Tier 3: Advanced (Architecture & Core Engine)
*Ideal for experienced developers interested in backend performance, file streaming, and testing frameworks.*

| Task | Description | Status | Key Files |
| :--- | :--- | :---: | :--- |
| **Automated Unit Test Suite** | Standard library `unittest` suite (`./scripts/run_tests.sh`) testing router & discovery. | ✅ Done | `tests/test_router.py`, `tests/test_discovery.py` |
| **Git Worktree Support** | Discover and visually group Git worktrees pointing to the same repository root. | ⏳ Open | `backend/router.py`, `frontend/app.js` |
| **Server-Sent Events (SSE)** | Stream repository status updates via standard library HTTP SSE when git index changes. | ⏳ Open | `backend/server.py` |

---

Thank you for helping make DevGit better for developers everywhere! 🎉
