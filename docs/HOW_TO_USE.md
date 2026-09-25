# 📖 DevGit User Guide: Examples & Walkthrough

A practical, step-by-step guide on how to run and use **DevGit** with real-world project setups.

---

## 📑 Table of Contents

1. [Real-World Project Scenarios](#1-real-world-project-scenarios)
   - [Scenario A: Flutter / Dart Melos Monorepo](#scenario-a-flutter--dart-melos-monorepo)
   - [Scenario B: JavaScript / TypeScript Monorepo](#scenario-b-javascript--typescript-monorepo-turborepo-npm-pnpm)
   - [Scenario C: Microservices with Multiple Repos](#scenario-c-microservices-with-multiple-repos)
   - [Scenario D: Single Standalone Repository](#scenario-d-single-standalone-repository)
2. [Step-by-Step UI Walkthrough](#2-step-by-step-ui-walkthrough)
   - [Step 1: Check Repo Status and Diffs](#step-1-check-repo-status-and-diffs)
   - [Step 2: Sync and Fetch All](#step-2-sync-and-fetch-all)
   - [Step 3: Generate AI Commit Messages](#step-3-generate-ai-commit-messages)
   - [Step 4: Manage Branches (Gitflow)](#step-4-manage-branches-gitflow)
   - [Step 5: Switch Workspace On-the-Fly](#step-5-switch-workspace-on-the-fly)
3. [Common Questions & Tips](#3-common-questions--tips)

---

## 1. Real-World Project Scenarios

### Scenario A: Flutter / Dart Melos Monorepo

**Folder structure:**
```text
my-flutter-workspace/
├── apps/
│   ├── customer_app/ (.git)
│   └── driver_app/   (.git)
├── packages/
│   ├── core_ui/      (.git)
│   └── api_client/   (.git)
└── melos.yaml
```

**How to run:**
```bash
./start.sh --workspace /path/to/my-flutter-workspace --open
```

**What DevGit does:**
- Automatically detects repos inside `apps/` and `packages/`.
- Enables the **Melos Git Workflow** toggle in the top bar.
- Groups cards into **Apps** and **Packages** sections.
- Supports scoped multi-repo branch actions and release tagging.

---

### Scenario B: JavaScript / TypeScript Monorepo (Turborepo, npm, pnpm)

**Folder structure:**
```text
my-turborepo/
├── .devgit.json
├── apps/
│   ├── web/  (.git)
│   └── docs/ (.git)
└── packages/
    ├── ui/     (.git)
    └── config/ (.git)
```

**How to run:**
1. Create an optional `.devgit.json` in the root:
```json
{
  "name": "My Web Monorepo",
  "groups": {
    "Web Apps": ["apps/*"],
    "Shared UI": ["packages/*"]
  }
}
```
2. Launch DevGit:
```bash
./start.sh --workspace /path/to/my-turborepo
```

**What DevGit does:**
- Scans `apps/` and `packages/` automatically.
- Shows branch sync, ahead/behind counters, and uncommitted changes across all packages simultaneously.

---

### Scenario C: Microservices with Multiple Repos

**Folder structure:**
```text
my-backend-cloud/
├── .devgit.json
├── auth-service/    (.git)
├── billing-service/ (.git)
├── order-service/   (.git)
└── gateway/         (.git)
```

**How to run:**
1. Add `.devgit.json` to tell DevGit about root folders:
```json
{
  "include": [
    "auth-service",
    "billing-service",
    "order-service",
    "gateway"
  ]
}
```
2. Start DevGit:
```bash
./start.sh --workspace /path/to/my-backend-cloud
```

**What DevGit does:**
- Surfaces every microservice repository as an independent card.
- Allows running **Git Fetch All** to update remotes across all 4 services with one click.

---

### Scenario D: Single Standalone Repository

**Folder structure:**
```text
my-single-project/
├── .git/
├── src/
└── README.md
```

**How to run:**
```bash
cd my-single-project
/path/to/dev-git/start.sh
```

**What DevGit does:**
- Detects the single root Git repository.
- Displays commit history, branch manager, conflict resolver, and AI commit generator for this single repo.

---

## 2. Step-by-Step UI Walkthrough

### Step 1: Check Repo Status and Diffs
1. Open `http://localhost:8086`.
2. Repositories with uncommitted changes show an amber **Dirty** badge.
3. Click the badge to view unstaged and staged file diffs with syntax highlighting.

### Step 2: Sync and Fetch All
1. Click **Git Fetch All** in the top right corner.
2. DevGit runs background fetches across all repositories in parallel.
3. If remote changes exist, cards show a blue **Behind (X)** badge.
4. Click **Pull** on any card to fast-forward.

### Step 3: Generate AI Commit Messages
*(Requires local [Ollama](https://ollama.com/) running with `ollama run llama3`)*
1. On any repository card with changes, click **AI Commit**.
2. Select files you want to include in the commit.
3. Click **Generate Message**. DevGit sends the git diff to local Ollama.
4. Review the generated conventional commit message (e.g. `feat(auth): add refresh token handler`).
5. Click **Commit & Push** or **Commit Locally**.

### Step 4: Manage Branches (Gitflow)
1. Click **Branches** on any card.
2. Select **Start Branch** to create a branch following conventions:
   - `feature/`
   - `bugfix/`
   - `hotfix/`
   - `release/`
3. Check **Automatically check out new branch** to switch immediately.
4. When finished, use the **Merge Branch** modal with the searchable branch picker to merge and delete.

### Step 5: Switch Workspace On-the-Fly
1. Notice the **WORKSPACE** label in the top header displaying your current directory.
2. Click the **Switch** button next to it.
3. Enter the absolute path to another project (e.g., `/path/to/other-monorepo`).
4. Click **Switch Workspace**. The dashboard refreshes with the new project's repositories instantly.

---

## 3. Common Questions & Tips

- **How do I customize app icons and colors?**  
  Edit `workspace_assets/apps_config.json` with your app names, brand colors, and icons.
- **Can I run DevGit on a different port?**  
  Yes: `./start.sh --port 9000`
- **Can I access DevGit from another computer on my LAN?**  
  Yes: `./start.sh --host 0.0.0.0`
- **Does DevGit send my code to the cloud?**  
  No. DevGit is 100% local. Even AI commit generation runs on your own machine through local Ollama.
