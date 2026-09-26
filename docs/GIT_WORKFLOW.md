# 🌿 Standard Git Workflow Practices in DevGit

This guide outlines the standard Git workflows supported and recommended when using and developing **DevGit**.

---

## 📑 Table of Contents

1. [Supported Workflow Models](#1-supported-workflow-models)
   - [Trunk-Based / GitHub Flow (Recommended for Fast Teams)](#a-trunk-based--github-flow-recommended)
   - [Gitflow Workflow (Recommended for Versioned Releases)](#b-gitflow-workflow)
2. [Branching Strategy & Naming Conventions](#2-branching-strategy--naming-conventions)
3. [Conventional Commits Standard](#3-conventional-commits-standard)
4. [Semantic Versioning & Release Tagging](#4-semantic-versioning--release-tagging)
5. [Multi-Repo & Monorepo Synchronization](#5-multi-repo--monorepo-synchronization)
6. [Best Practices for Daily Work](#6-best-practices-for-daily-work)

---

## 1. Supported Workflow Models

DevGit supports both **Trunk-Based Development** and classical **Gitflow**. You can toggle workflows and switch branch views directly from the DevGit interface.

### A. Trunk-Based / GitHub Flow (Recommended)

In Trunk-Based development, `main` is always stable and releasable. Developers create short-lived feature branches, submit Pull Requests, and merge back into `main` after CI checks pass.

```text
main:        ─────●───────────●──────────●──────────●─── (Always Deployable)
                  │           ▲          │          ▲
feature/pr:       └──●──●──●──┘          └──●──●────┘
                  (Short-lived, < 2 days)
```

**Key Principles:**
- Branches live for 1 to 2 days maximum.
- Features are merged through Pull Requests with peer review.
- Continuous deployment directly from `main`.

---

### B. Gitflow Workflow

For projects requiring scheduled release cycles and hotfix isolation:

```text
main:        ─────●─────────────────────────────●──────── (Production v1.0.0, v1.1.0)
                  │                             ▲
release:          │                  ┌──●──●────┘ (release/v1.1.0)
                  │                  ▲
develop:     ─────●───●──────●───────●──●───────●──────── (Active integration)
                      │      ▲
feature:              └──●───┘ (feature/login-oauth)
```

- **`main`**: Reflects production state. Every commit is tagged (`v1.0.0`).
- **`develop`**: Daily integration branch for completed features.
- **`feature/*`**: Branched from `develop`, merged back into `develop`.
- **`release/*`**: Branched from `develop`, merged into both `main` and `develop`.
- **`hotfix/*`**: Urgent production bug fixes branched directly from `main`.

---

## 2. Branching Strategy & Naming Conventions

Use standardized prefixes for every branch created in DevGit:

| Prefix | Type | Purpose | Base Branch |
| :--- | :--- | :--- | :--- |
| `feat/` or `feature/` | Feature | New user-facing feature or enhancement | `main` or `develop` |
| `fix/` or `bugfix/` | Bug Fix | Non-urgent defect correction | `main` or `develop` |
| `hotfix/` | Urgent Fix | Critical production patch | `main` |
| `release/` | Release | Release staging and stabilization | `develop` |
| `docs/` | Docs | Documentation only | `main` |
| `refactor/` | Refactor | Code restructuring with no behavior change | `main` or `develop` |
| `chore/` | Housekeeping| Dependencies, tooling, or build scripts | `main` |
| `test/` | Testing | Adding or modifying unit/e2e tests | `main` or `develop` |

### Examples:
```bash
git checkout -b feat/multi-workspace-switcher
git checkout -b fix/detached-head-status
git checkout -b docs/workflow-guide
git checkout -b release/v1.2.0
```

---

## 3. Conventional Commits Standard

DevGit’s built-in **AI Commit Message Generator** and git tools generate and encourage [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>): <subject in present tense>

[optional body providing technical context]

[optional footer(s)]
```

### Commit Types:
- `feat`: New feature for the user or consumer.
- `fix`: Bug fix for the user or consumer.
- `docs`: Documentation updates.
- `style`: Formatting, whitespace (no production code change).
- `refactor`: Refactoring code without behavioral difference.
- `perf`: Performance enhancement.
- `test`: Adding or correcting tests.
- `build`: Changes that affect the build system or packaging (`pyproject.toml`).
- `ci`: Changes to CI configuration and scripts.
- `chore`: Auxiliary tool changes or housekeeping.

### Example Messages:
```text
feat(discovery): support custom monorepo layouts via .devgit.json

fix(branches): handle branch names with slashes in API endpoints

docs(workflow): add comprehensive Git workflow practices guide
```

---

## 4. Semantic Versioning & Release Tagging

Follow [Semantic Versioning 2.0.0](https://semver.org/) for all release tags:

$$\text{v}\mathbf{MAJOR}.\mathbf{MINOR}.\mathbf{PATCH}$$

- **MAJOR**: Incompatible API changes or breaking redesigns.
- **MINOR**: Backward-compatible new functionality.
- **PATCH**: Backward-compatible bug fixes and stability tweaks.

### Tagging via Git CLI or DevGit Console:
```bash
# Create annotated tag
git tag -a v1.2.0 -m "Release v1.2.0: multi-workspace support"

# Push tag to remote
git push origin v1.2.0
```

---

## 5. Multi-Repo & Monorepo Synchronization

When working across multiple repositories in a monorepo (such as Melos Dart/Flutter workspaces, Turborepos, or microservices):

1. **Keep Branches Synchronized**: Use DevGit’s **"Batch Branch"** creation to create matching branch names across all affected packages simultaneously.
2. **Review Multi-Repo Diffs**: Inspect staged and unstaged diffs across all sub-repos simultaneously before pushing.
3. **Atomic Verification**: Ensure related PRs across multiple repositories reference the same feature ticket or issue number (e.g. `feat(core): update auth [PROJ-102]`).

---

## 6. Best Practices for Daily Work

1. **Pull Frequently**: Run `Sync All` in DevGit or `git fetch --all --prune` daily to stay up to date.
2. **Rebase Before Merging**: Keep Git history linear and clean:
   ```bash
   git fetch origin
   git rebase origin/main
   ```
3. **Small, Atomic Commits**: Avoid committing unrelated changes together. One logical fix or feature per commit.
4. **Clean Stashes**: Delete temporary stashes once applied:
   ```bash
   git stash list
   git stash pop
   git stash drop
   ```
