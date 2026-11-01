#!/usr/bin/env bash
# Stop the DevGit server listening on DEVGIT_PORT (default 8086).
set -euo pipefail
PORT="${DEVGIT_PORT:-8086}"

pids="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN || true)"
if [ -z "$pids" ]; then
  echo "No DevGit server listening on port ${PORT}."
  exit 0
fi

kill $pids
for _ in $(seq 1 20); do
  lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || { echo "DevGit server on port ${PORT} stopped."; exit 0; }
  sleep 0.25
done

echo "Still running, forcing kill..."
kill -9 $pids
echo "DevGit server on port ${PORT} stopped."
