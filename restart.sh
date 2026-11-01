#!/usr/bin/env bash
# Stop the DevGit server (if running) and start it again. Extra args go to start.sh.
# Set WORKSPACE_ROOT to choose the workspace (default: current directory).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/stop.sh"
exec "${SCRIPT_DIR}/start.sh" "$@"
