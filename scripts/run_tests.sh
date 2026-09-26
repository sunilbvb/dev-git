#!/usr/bin/env bash
# ==============================================================================
# Run DevGit Automated Test Suite
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🧪 Running DevGit Test Suite..."
python3 -m unittest discover -s "$ROOT_DIR/tests" -p "test_*.py" -v
echo "✅ All tests passed successfully!"
