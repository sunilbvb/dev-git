#!/usr/bin/env bash
# ==============================================================================
# Sync local UI design system bundle from developer-dashboard-ui GitHub repo
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_FILE="$ROOT_DIR/frontend/css/ui.css"
SOURCE_URL="https://raw.githubusercontent.com/sunilbvb/developer-dashboard-ui/main/dist/ui.css"

echo "🔄 Syncing UI stylesheet from $SOURCE_URL..."
curl -sSL --fail "$SOURCE_URL" -o "$TARGET_FILE"

echo "✅ Successfully synced UI bundle to $TARGET_FILE ($(wc -c < "$TARGET_FILE" | tr -d ' ') bytes)"
