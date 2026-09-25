#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export WORKSPACE_ROOT="${WORKSPACE_ROOT:-$(pwd)}"
python3 "${SCRIPT_DIR}/backend/server.py" "$@"
