# 🔄 DevGit — Standalone Multi-Repo Git Dashboard

A lightweight, zero-dependency, local web-based dashboard designed for managing Git repositories across monorepos, multi-repo projects (`apps/`, `packages/`, `tools/`), and standalone workspaces.

---

## ✨ Features

- **Automatic Repository Discovery:**
  - Scans single Git repos, multi-repo structures (`apps/`, `packages/`, `tools/`, `services/`, `libs/`), and custom configurations via `.devgit.json`.
  - Supports Flutter/Dart Melos multi-package workspaces and custom folder layouts.
- **Multi-Repo Status at a Glance:**
  - Visual grid overview of dirty working trees, untracked changes, and diverged branches.
  - Ahead/behind commit tracking against remote branches.
- **On-the-Fly Workspace Switching:**
  - Switch target projects directly from the web UI top bar without restarting the server.
- **Batch Git Operations:**
  - One-click **Fetch All** across all repositories in the workspace.
  - Sync, branch creation, fast-forward pulls, pushes, and stashes.
- **AI-Powered Commit Messages:**
  - Generate semantic, conventional commit messages using local AI models via [Ollama](https://ollama.com/) (e.g. `llama3`, `deepseek-r1`).
  - Completely local and private — no third-party cloud API keys required.
- **Branch & Release Management:**
  - Visual Gitflow branch creation, finish/merge, checkout, and deletion.
  - Interactive conflict resolution and stash pull/pop management.
  - Tag creation, version bumping (SemVer), and GitHub-ready release summaries.
- **Embedded Interactive Terminal:**
  - Run Git commands directly within specific repositories from the web UI.
- **Zero Heavy Dependencies:**
  - Backend runs entirely on Python standard library (`http.server`).
  - No Node.js runtime, build steps, or heavyweight database required.

---

> 💡 **Looking for step-by-step examples?** Check out the practical [User Guide & Walkthrough](docs/HOW_TO_USE.md) covering Flutter Melos, Turborepo, microservices, and full UI workflows.

---

## 🚀 Quick Start

### 1. Requirements

- **Python 3.8+**
- **Git 2.20+**
- *(Optional)* [Ollama](https://ollama.com/) installed and running locally for AI commit generation.

### 2. Launching DevGit

Start DevGit pointing to your current directory:

```bash
./start.sh
```

Or target any workspace directly via CLI flag:

```bash
./start.sh --workspace /path/to/my-monorepo
```

Or open browser automatically:

```bash
./start.sh --open
```

Open your browser at **`http://localhost:8086`**.

### 3. Installation as CLI Tool

You can also install DevGit into your Python environment:

```bash
pip install .
devgit --open
```

---

## 🛠️ CLI Options

You can pass standard flags directly to `./start.sh` or `backend/server.py`:

```bash
python3 backend/server.py --help

Options:
  -w, --workspace PATH   Path to target workspace root (default: current directory)
  -p, --port PORT        HTTP server port (default: 8086)
  --host HOST            HTTP host binding (default: 127.0.0.1)
  -o, --open             Automatically open DevGit in default web browser
```

---

## 📁 Repository Discovery Strategy

DevGit scans the target `WORKSPACE_ROOT` using the following hierarchy:
1. **Custom Configuration (`.devgit.json`):** If present in the target workspace, uses custom `include`, `groups`, and `exclude` paths.
2. **Single Repository:** Checks if `WORKSPACE_ROOT/.git` exists.
3. **Multi-Repo Folders:** Scans for nested Git repos in standard monorepo folders:
   - `apps/`
   - `packages/`
   - `tools/` / `tool/`
   - `services/`
   - `libs/`
4. **Fallback Scan:** Recursively traverses the workspace directory while ignoring build caches, dependencies, and temporary folders (`node_modules`, `.dart_tool`, `Pods`, `build`, etc.).

---

## ⚙️ Configuration & Customization

### Custom Workspace Layout (`.devgit.json`)

To customize which directories are scanned in your monorepo, place a `.devgit.json` file in your workspace root:

```json
{
  "name": "My Monorepo",
  "groups": {
    "Apps": ["apps/*"],
    "Shared": ["packages/*"],
    "Services": ["services/*"]
  },
  "include": ["apps", "packages", "libs"],
  "exclude": ["dist", "experimental"]
}
```

### Local AI Commit Generator (Ollama)

DevGit connects to a local Ollama instance for AI commit messages. You can customize the model and endpoint via environment variables:

```bash
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3"      # or "deepseek-r1:latest", "mistral", etc.
./start.sh
```

### App Metadata Configuration

You can customize app display names, icons, and colors by adding a configuration file at `workspace_assets/apps_config.json`:

```json
[
  {
    "id": "my_app",
    "name": "My App",
    "color": "#3b82f6",
    "icon": "package",
    "version": "1.0.0"
  }
]
```

### UI Design System Integration

DevGit is styled with the [`developer-dashboard-ui`](https://github.com/sunilbvb/developer-dashboard-ui) design system. It is delivered via CDN for instant global updates with an offline fallback. To manually sync or update the local fallback stylesheet:

```bash
./scripts/sync-ui.sh
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
