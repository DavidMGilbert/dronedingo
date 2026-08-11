#!/usr/bin/env bash
# ============================================================================
#  DroneDingo self-update — pull, reinstall deps, restart.
#  Invoked by the web UI via a narrow sudoers rule (see install.sh). Not meant
#  to be run interactively, though it is safe to.
# ============================================================================
set -euo pipefail

APP_DIR=/opt/dronedingo
BRANCH="${1:-main}"
LOG=/var/log/dronedingo-update.log
exec > >(tee -a "$LOG") 2>&1

echo "== DroneDingo update $(date -Is) =="

cd "$APP_DIR"

if [[ -d .git ]]; then
  echo "Fetching latest ($BRANCH)…"
  git fetch --quiet origin "$BRANCH"
  git reset --hard "origin/$BRANCH"
else
  echo "Not a git checkout; nothing to pull." >&2
  exit 1
fi

echo "Updating dependencies…"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/backend/requirements.txt"

echo "Restarting service…"
systemctl restart dronedingo

echo "== Update complete =="
