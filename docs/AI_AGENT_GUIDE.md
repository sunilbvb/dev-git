# DevGit — AI Agent Guide

How an AI agent uses DevGit to do **Git handling only** (branches, sync, status, tags) across a multi-repo workspace such as TYRIOS. Read this before calling any DevGit endpoint.

> Verified against the source in `devgit/` (server.py, router.py, modules/*). Items marked **(unverified)** were not exercised end-to-end.

---

## 1. Scope and ground rules

- DevGit is for **Git handling**. Do **not** read, analyse, or change application code unless the user asks separately.
- **Never commit, push, tag, merge, delete branches, or force anything without explicit user approval.** Branch creation, checkout, fetch and pull are the default safe set once the user has approved the task.
- On any error: **stop, report the exact error to the user, and wait.** Do not improvise a workaround that changes more than the user approved.
- Never print or store the session token in replies, logs, or files.
- Keep replies short. Report per-repo results as a compact table.

---

## 2. Connecting

- Server: `http://localhost:8086` (default; `./start.sh --port N` changes it). Only `localhost` Host/Origin headers are accepted.
- Auth: every `/api/*` call needs the session token, as header `X-DevGit-Token: <token>` (or `?token=` query).
- The token is random per server start and is printed in the terminal (`Session Token:` / dashboard URL `?token=...`). **An agent cannot discover it.** Ask the user for it, or have the user start the server with a fixed token:
  ```bash
  DEVGIT_TOKEN=<chosen-token> ./start.sh
  ```
- Verify the connection and active workspace first:
  ```bash
  curl -s -H "X-DevGit-Token: $T" localhost:8086/api/workspace
  ```
  Expect `{"success": true, "workspace": "<path>", "name": "<name>"}`. If the workspace is wrong, stop and tell the user (switching is `POST /api/workspace/switch` with `{"workspace": "<abs path>"}`, only on user request).

All responses are JSON with `success: true|false` and, on failure, `error`.

---

## 3. API reference (Git subset)

Every repo operation takes `repoPath`, an **absolute path of a repo discovered in the active workspace**. Unknown paths return `Unknown repoPath`. Branch names are validated (no spaces, `;&|` backtick `$`, leading `-`, `..`).

### Read (GET)

| Endpoint | Query | Returns |
| :--- | :--- | :--- |
| `/api/git/repos` | — | All discovered repos: `name`, `branch`, `path`, dirty/ahead/behind info |
| `/api/git/branches` | `repoPath`, `quick=true` (optional) | Current branch, local/remote branches |
| `/api/git/status` | `repoPath` | Working tree status |
| `/api/git/commits` | `repoPath` | Recent commits |
| `/api/git/diff`, `/api/git/changes` | `repoPath` | Diffs / changed files |
| `/api/git/stashes` | `repoPath` | Stash list |
| `/api/git/conflicts` | `repoPath` | Conflicted files |
| `/api/git/tags` (POST) | `repoPath` | Tag list (note: POST) |

### Write (POST, JSON body)

| Endpoint | Body | Behaviour |
| :--- | :--- | :--- |
| `/api/git/fetch` | `scope` (`all`\|`one`), `repoPath` (if `one`) | `git fetch` |
| `/api/git/pull` | `repoPath` | Pull current branch |
| `/api/git/branch/create` | `repoPath`, `branchName`, `checkout` (default `true`) | `git checkout -b <name>` — **from the current HEAD, not from a chosen base** (see §5) |
| `/api/git/branch/action` | `repoPath`, `branch`, `action`, extras | Actions below. **Refuses if the working tree is dirty.** |
| `/api/git/branch/delete` | `repoPath`, `branchName`, `force` | Delete branch. **Needs user approval.** |
| `/api/git/branch/finish` | `repoPath`, `branchName`, `baseBranch`, `deleteBranch` | Merge into base and push. **Needs user approval.** |
| `/api/git/commit` | `repoPath`, `message`, `stageAll` | **Needs user approval.** |
| `/api/git/push` | `repoPath`, `force` | **Needs user approval.** |
| `/api/git/stash/create` | `repoPath`, `message`, `includeUntracked` | Stash |
| `/api/git/stash/apply\|pop\|drop` | `repoPath`, `stashRef` | Stash ops |
| `/api/git/tag/create` | `repoPath`, `tagName`, `message`, `pushToRemote` | **Needs user approval.** |

`/api/git/branch/action` `action` values: `pull`, `push`, `fetch`, `checkout`, `rename` (`newBranch`, `remote`), `merge`, `merge-current-into-this`, `merge-this-into-current`, `rebase`.

- `pull`: checks out `branch`, then pulls it.
- `checkout`: if `branch` does not exist it returns `{"success": true, "prompt": true, ...}` (nothing changed) unless `createMissingMap` is sent. Treat `prompt: true` as "branch missing" — do not assume it was created.
- `push`, `merge*`, `rename` with `remote: true`, `rebase` change history or the remote. **Ask first.**

`githubToken` (optional body field) is a GitHub token for remote operations. Do not invent or request one unless the user supplies it.

---

## 4. Branch conventions

From [GIT_WORKFLOW.md](GIT_WORKFLOW.md) and the TYRIOS repos:

| Prefix | Use | Base |
| :--- | :--- | :--- |
| `hotfix/` | Urgent production fix | `main` |
| `bugfix/` | Non-urgent fix | `develop` |
| `feature(s)/` | New feature | `develop` |
| `release(s)/` | Release stabilisation | `develop` |

Naming seen in TYRIOS: `<prefix>/v<version>/<ticket-name>`, e.g. `bugfix/v1.1.3/tablet-login-keyboard-issue`, `releases/v1.0.5/coach-mark-integrations`, `hotfix/v1.0.8/<ticket-name>`.

Always ask the user for the **prefix, version and ticket name** if any is missing. Never guess a version.

---

## 5. Multi-repo (Melos) behaviour

TYRIOS is a Melos workspace. The app (`apps/gyo_business`) and each package (`packages/*`) are **separate Git repos**. A change to an app usually needs the same branch in its dependent packages.

How the tool does it (from `frontend/gitflow_panel.js` and the TYRIOS `Makefile`/`pubspec.yaml`):

```bash
make git-gyo-business CMD="checkout -b <branch> <base>"
# -> melos run git:gyo_business -- <CMD>
# -> melos exec --scope=gyo_business --include-dependencies -- bash tool/scripts/smart_git.sh
```

- App scope target: `apps/<app_name>` -> `make git-<app-name-kebab>`; workspace-wide: `make git-all`.
- Dependency list for an app: `melos list --scope=<app> --include-dependencies` (read-only). Melos package names do not always equal repo folder names (e.g. `login_logic` lives inside the `social_logins` repo) — map packages to repos by path before acting.
- **Naming rule (matches the Start Branch UI):** the **app** repo gets `<prefix>/<version>/<ticket>`; every **package** repo gets `<prefix>/<app-kebab>/<version>/<ticket>`. Example: app `hotfix/v1.0.8/x`, packages `hotfix/gyo-business/v1.0.8/x`.

### DevGit does the fan-out itself

DevGit must not depend on scripts in the workspace (the TYRIOS `smart_git.sh` is gone and is not DevGit's concern). Use the built-in endpoint:

`POST /api/git/branch/create-scoped` (or `/api/git/branch/create` with `"useMelos": true`) with `{"repoPath": "<app repo>", "branchName": "<app branch name>", "baseBranch": "main", "dryRun": true|false, "skipExisting": false}`

- Resolves the app's dependent packages with `melos list --scope=<app> --include-dependencies --json`, maps them to their own repos. `branchName` is the **app** name; package repos get the app name nested in (see naming rule).
- Packages with no repo of their own (they live in the workspace root repo) are **skipped** and listed in `skippedPackages`. The workspace root repo is never branched.
- Pre-checks every repo first (clean tree, base exists). If any fails, **nothing is changed**.
- If the branch already exists somewhere it returns `alreadyExists`, `existingRepos`, `missingRepos` and changes nothing; re-send with `skipExisting: true` to create it only in the missing repos (ask the user first).
- Then per repo: checkout base, `pull --ff-only`, `checkout -b <branch>`. Stops at the first failure and says which repos already changed.
- **Always run `dryRun: true` first.** `/api/git/branch/create-scoped` only exists in the `devgit/` package (`python3 -m devgit`); the old `backend/` server would match `/api/git/branch/create` by prefix and create one unscoped branch from HEAD.

---

## 6. Runbook: start a hotfix (app + dependent packages)

Inputs needed from the user: app, version, ticket name, and which repos to include. Branch name: `hotfix/v<version>/<ticket-name>`.

1. `GET /api/workspace` -> correct workspace; `GET /api/git/repos` -> note each repo's branch.
2. `POST /api/git/branch/create-scoped` with `dryRun: true`. Show the repo table to the user. If any repo is dirty or the branch exists, stop and report.
3. After the user approves: same call with `dryRun: false`.
4. `GET /api/git/repos` -> confirm every listed repo is on the new branch.

**Report**: table of repo | previous branch | result | error. Do not commit or push. Pushing and PRs go to the user.

**After the hotfix is released (user-driven)**: merge back into `develop` so the fix is not lost.

---

## 7. Other runbooks (same pattern)

- **Feature / bugfix**: as §6 but base is `develop` (pull `develop`, then create `feature(s)/...` or `bugfix/...`).
- **Sync all**: `POST /api/git/fetch {"scope":"all"}`, then report ahead/behind from `/api/git/repos`. Pull only repos that are clean and behind.
- **Status report**: `GET /api/git/repos`, summarise dirty / ahead / behind / branch per repo.

---

## 8. Errors and what to do

| Error / signal | Meaning | Agent action |
| :--- | :--- | :--- |
| HTTP 401 `Unauthorized` | Missing/wrong token | Ask user for token. Do not retry in a loop. |
| HTTP 403 `Invalid Host or Origin` | Not calling localhost | Use `localhost:8086`. |
| `Unknown repoPath` | Path is not a discovered repo | Re-read `/api/git/repos`; use exact paths. |
| `Working tree has uncommitted changes` / `dirty: true` | Dirty repo | Skip repo, report. Never stash/discard unasked. |
| `Invalid branchName: ...` | Fails ref validation | Fix the name with the user. |
| `prompt: true` on checkout | Branch missing | Nothing was changed. Report. |
| `Failed to create branch ...` | Often: already exists | Report; do not delete or force. |
| `make: ... smart_git.sh: No such file` | Known issue §5 | Stop and report. |
| Push/merge/pull conflict or auth failure | Remote or merge problem | Stop and report the exact text. |

Default for anything not listed: **stop and tell the user.**

---

## 9. Improvements worth making to the tool

- Add a way for agents to get the token (e.g. `--print-token`, or a token file with `0600` permissions).
- Add a base-branch option to `branch/create` so it can branch from `main` in one call.
- Consolidate `backend/` and `devgit/`: two diverged copies exist, and `start.sh` runs the older `backend/` one.
