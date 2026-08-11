#!/usr/bin/env bash
# ============================================================================
#  SkyWarden installer — Raspberry Pi OS (Trixie) Lite 64-bit
#  Usage:  sudo bash deploy/install.sh
# ============================================================================
set -euo pipefail

APP_DIR=/opt/skywarden
SERVICE_USER=skywarden

echo "== SkyWarden install =="

# 1. System deps
apt-get update
apt-get install -y python3 python3-venv python3-pip git \
  librtlsdr0 rtl-sdr libatlas-base-dev

# 2. App user + location
id -u "$SERVICE_USER" &>/dev/null || useradd -r -s /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$APP_DIR"
# Copy the repo contents (run this from the cloned repo root)
rsync -a --exclude .git --exclude .venv --exclude data ./ "$APP_DIR"/

# 3. Python environment
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"

# Optional capture stacks — uncomment to enable on this node:
# "$APP_DIR/.venv/bin/pip" install scapy pyrtlsdr numpy bleak

mkdir -p "$APP_DIR/data"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

# 4. systemd service
cp "$APP_DIR/deploy/skywarden.service" /etc/systemd/system/skywarden.service
systemctl daemon-reload
systemctl enable --now skywarden

echo
echo "== Done. SkyWarden is running. =="
echo "   UI:     http://$(hostname -I | awk '{print $1}'):8000"
echo "   Logs:   journalctl -u skywarden -f"
echo "   Config: $APP_DIR/config/skywarden.yaml"
