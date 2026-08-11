#!/usr/bin/env bash
# ============================================================================
#  Reset the DroneDingo admin login — run from the Pi console when locked out.
#
#    sudo bash /opt/dronedingo/deploy/reset-admin.sh                # interactive
#    sudo bash /opt/dronedingo/deploy/reset-admin.sh --clear        # wipe -> web setup
#    sudo DRONEDINGO_ADMIN_EMAIL=a@b.com DRONEDINGO_ADMIN_PASSWORD=secret \
#         bash /opt/dronedingo/deploy/reset-admin.sh                # non-interactive
#
#  There is intentionally NO web-based reset: if you are locked out of the web
#  UI you must be at the console (or have SSH), which is the security boundary.
# ============================================================================
set -euo pipefail
APP_DIR=/opt/dronedingo
PY="$APP_DIR/.venv/bin/python"

if [[ ! -x "$PY" ]]; then echo "DroneDingo not installed at $APP_DIR"; exit 1; fi

if [[ "${1:-}" == "--clear" ]]; then
  DD_APP="$APP_DIR" "$PY" - <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["DD_APP"], "backend"))
from app import auth
auth.reset()
print("Admin credentials cleared — set a new admin on the next web visit.")
PYEOF
else
  EMAIL="${DRONEDINGO_ADMIN_EMAIL:-}"
  PASS="${DRONEDINGO_ADMIN_PASSWORD:-}"
  [[ -z "$EMAIL" ]] && read -rp  "New admin email: " EMAIL
  [[ -z "$PASS"  ]] && { read -rsp "New admin password (min 8 chars): " PASS; echo; }
  DD_E="$EMAIL" DD_P="$PASS" DD_APP="$APP_DIR" "$PY" - <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["DD_APP"], "backend"))
from app import auth
auth.set_credentials(os.environ["DD_E"], os.environ["DD_P"])
print("Admin login updated for", os.environ["DD_E"])
PYEOF
fi

# state.json must stay owned by the service user, and drop any live sessions.
chown -R dronedingo:dronedingo "$APP_DIR/data" 2>/dev/null || true
systemctl restart dronedingo 2>/dev/null || true
echo "Done."
