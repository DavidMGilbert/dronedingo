#!/usr/bin/env bash
# ============================================================================
#  DroneDingo — single-command installer for Raspberry Pi OS (Trixie) Lite 64-bit
#
#      curl -fsSL https://raw.githubusercontent.com/DavidMGilbert/dronedingo/main/deploy/install.sh | sudo bash
#  or, from a clone:
#      sudo bash deploy/install.sh
#
#  Installs and configures everything and leaves the appliance running.
#  All third-party stacks install quietly in the background; progress is shown
#  as high-level steps and the full detail is captured in the install log.
# ============================================================================
set -euo pipefail

APP_DIR=/opt/dronedingo
SERVICE_USER=dronedingo
REPO_URL="https://github.com/DavidMGilbert/dronedingo.git"
LOG=/var/log/dronedingo-install.log
: > "$LOG"

if [[ $EUID -ne 0 ]]; then echo "Please run with sudo."; exit 1; fi

BRAND="DroneDingo"
step() { printf "\033[1;36m[%s]\033[0m %s\n" "$BRAND" "$1"; }
run()  { echo "+ $*" >>"$LOG"; "$@" >>"$LOG" 2>&1; }

export DEBIAN_FRONTEND=noninteractive

step "Installing system components…"
run apt-get update -qq
# Core runtime + RTL-SDR library/tools + wifi tooling. Quiet, unattended.
run apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip git rsync \
    librtlsdr0 rtl-sdr usbutils iw

# Ensure the DVB kernel driver doesn't grab the RTL-SDR (standard SDR setup).
if [[ ! -f /etc/modprobe.d/dronedingo-rtlsdr.conf ]]; then
  echo "blacklist dvb_usb_rtl28xxu" > /etc/modprobe.d/dronedingo-rtlsdr.conf
  run modprobe -r dvb_usb_rtl28xxu || true
fi

step "Placing application in $APP_DIR…"
id -u "$SERVICE_USER" &>/dev/null || run useradd -r -m -s /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$APP_DIR"
# If piped from curl (no local repo), clone; otherwise copy the working tree.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || true)"
if [[ -n "$SRC_DIR" && -f "$SRC_DIR/backend/requirements.txt" ]]; then
  run rsync -a --exclude .git --exclude .venv --exclude data "$SRC_DIR"/ "$APP_DIR"/
else
  rm -rf "$APP_DIR/.src"
  run git clone --depth 1 "$REPO_URL" "$APP_DIR/.src"
  run rsync -a --exclude .git --exclude .venv --exclude data "$APP_DIR/.src"/ "$APP_DIR"/
  rm -rf "$APP_DIR/.src"
fi

step "Setting up the Python environment (quietly)…"
run python3 -m venv "$APP_DIR/.venv"
run "$APP_DIR/.venv/bin/pip" install --upgrade pip
run "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
# Note: no GPL packages are installed — the capture stack is first-party and
# uses only the Python standard library. librtlsdr comes from apt, above.

mkdir -p "$APP_DIR/data"

step "Detecting attached hardware…"
enable_src() { run "$APP_DIR/.venv/bin/python" -c \
  "import sys; sys.path.insert(0,'$APP_DIR/backend'); from app import config; config.set_source_enabled('$1', True)"; }

# RTL-SDR (Realtek RTL2832U) — auto-enable the presence scanner if present.
if lsusb 2>/dev/null | grep -qiE '0bda:(2832|2838)|RTL2838|RTL2832'; then
  step "  • RTL-SDR found — enabling RF presence scanner."
  enable_src rtlsdr_scan
fi
# A second wireless interface is a candidate monitor-mode Remote ID receiver.
MON_IF="$(iw dev 2>/dev/null | awk '/Interface/{print $2}' | grep -v '^wlan0$' | head -1 || true)"
if [[ -n "${MON_IF:-}" ]]; then
  step "  • Secondary WiFi ($MON_IF) found — see notes to enable Remote ID capture."
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

step "Authorising privileged actions (updates, network, reboot)…"
# The web process runs unprivileged; these narrow sudoers rules let it invoke
# ONLY the two helper scripts (and nothing else) without a password. The
# helpers themselves constrain what can be done.
chmod +x "$APP_DIR/deploy/update.sh" "$APP_DIR/deploy/sysctl.sh" 2>/dev/null || true
cat > /etc/sudoers.d/dronedingo <<SUDO
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/bash $APP_DIR/deploy/update.sh, /bin/bash $APP_DIR/deploy/update.sh, /usr/bin/bash $APP_DIR/deploy/sysctl.sh, /bin/bash $APP_DIR/deploy/sysctl.sh
SUDO
chmod 440 /etc/sudoers.d/dronedingo
visudo -c -f /etc/sudoers.d/dronedingo >/dev/null 2>&1 || { echo "sudoers check failed"; rm -f /etc/sudoers.d/dronedingo; }

step "Installing and starting the service…"
cp "$APP_DIR/deploy/dronedingo.service" /etc/systemd/system/dronedingo.service
run systemctl daemon-reload
run systemctl enable dronedingo
run systemctl restart dronedingo

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

  ✅ $BRAND is installed and running.

     Dashboard : http://${IP:-<pi-ip>}:8000
     Logs      : journalctl -u dronedingo -f
     Config    : $APP_DIR/config/dronedingo.yaml
     Install log: $LOG

  Enable the radios you have (then: systemctl restart dronedingo):
     • WiFi Remote ID (identity + GPS):
         sudo bash $APP_DIR/deploy/monitor-mode.sh ${MON_IF:-wlan1}
         then set sources.wifi_remoteid.enabled: true (interface: ${MON_IF:-wlan1})
     • Bluetooth Remote ID:
         set sources.bt_remoteid.enabled: true
     • RTL-SDR presence: auto-enabled if a dongle was detected.

EOF
