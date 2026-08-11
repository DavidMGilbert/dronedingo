#!/usr/bin/env bash
# ============================================================================
#  DroneDingo self-update. Invoked by the web UI via a narrow sudoers rule.
#
#      update.sh git [branch]                 # developer git-checkout flow
#      update.sh from-zip <zip> <ver> <sha256># website signed-release flow
#
#  For from-zip the web process has ALREADY verified sha256 + Ed25519 signature;
#  this script re-checks the sha256 before touching anything, then swaps the
#  app tree while preserving data/ and the operator's config, and rolls back if
#  the service fails to come up.
# ============================================================================
set -euo pipefail

APP_DIR=/opt/dronedingo
LOG=/var/log/dronedingo-update.log
exec > >(tee -a "$LOG") 2>&1
echo "== DroneDingo update $(date -Is) =="

mode="${1:-git}"

restart_and_check() {
  echo "Restarting service…"
  systemctl restart dronedingo
  sleep 4
  systemctl is-active --quiet dronedingo
}

# ---------------------------------------------------------------- git flow ---
if [[ "$mode" == "git" ]]; then
  branch="${2:-main}"
  cd "$APP_DIR"
  [[ -d .git ]] || { echo "Not a git checkout." >&2; exit 1; }
  echo "Fetching latest ($branch)…"
  git fetch --quiet origin "$branch"
  git reset --hard "origin/$branch"
  "$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/backend/requirements.txt"
  restart_and_check
  echo "== Update complete =="
  exit 0
fi

# ------------------------------------------------------------ website flow ---
if [[ "$mode" == "from-zip" ]]; then
  zip="${2:?zip path required}"
  version="${3:?version required}"
  expected="${4:?sha256 required}"

  [[ -f "$zip" ]] || { echo "Zip not found: $zip" >&2; exit 1; }

  echo "Re-verifying checksum…"
  actual="$(sha256sum "$zip" | cut -d' ' -f1)"
  if [[ "$actual" != "$expected" ]]; then
    echo "Checksum mismatch (root re-check) — aborting." >&2
    exit 1
  fi

  staging="$APP_DIR/data/updates/stage-$version"
  backup="$APP_DIR/data/updates/backup-$(date +%s)"
  rm -rf "$staging"; mkdir -p "$staging"
  echo "Unpacking $version…"
  unzip -q "$zip" -d "$staging"

  # The zip may or may not wrap everything in a top-level dir; normalise.
  if [[ ! -d "$staging/backend" ]]; then
    inner="$(find "$staging" -maxdepth 2 -type d -name backend | head -1)"
    [[ -n "$inner" ]] && staging="$(dirname "$inner")"
  fi
  [[ -d "$staging/backend" ]] || { echo "Release layout invalid." >&2; exit 1; }

  echo "Backing up current build…"
  mkdir -p "$backup"
  # Copy the code dirs we are about to replace (not data/ or config).
  for d in backend frontend deploy; do
    [[ -e "$APP_DIR/$d" ]] && cp -a "$APP_DIR/$d" "$backup/"
  done

  echo "Applying new files (preserving data/ and config)…"
  # rsync in the new tree; NEVER touch data/ or the operator's live config.
  rsync -a --delete \
    --exclude 'data/' \
    --exclude 'config/dronedingo.yaml' \
    "$staging"/ "$APP_DIR"/

  echo "Updating dependencies…"
  "$APP_DIR/.venv/bin/pip" install --quiet --upgrade -r "$APP_DIR/backend/requirements.txt"

  chown -R dronedingo:dronedingo "$APP_DIR" 2>/dev/null || true

  if restart_and_check; then
    echo "$version" > "$APP_DIR/VERSION" 2>/dev/null || true
    rm -rf "$staging" "$zip"
    echo "== Update to $version complete =="
    exit 0
  fi

  echo "Service failed to start — rolling back." >&2
  for d in backend frontend deploy; do
    [[ -e "$backup/$d" ]] && { rm -rf "$APP_DIR/$d"; cp -a "$backup/$d" "$APP_DIR/"; }
  done
  "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt" || true
  systemctl restart dronedingo || true
  echo "== Rolled back to previous build ==" >&2
  exit 1
fi

echo "unknown mode: $mode" >&2
exit 2
