#!/usr/bin/env bash
# ============================================================================
#  DroneDingo — single-command installer for Raspberry Pi OS (Trixie) Lite 64-bit
#
#  While the repo is PRIVATE, clone it on the Pi (with your GitHub credentials)
#  then run the installer from the clone — this uses the local working tree and
#  needs no further repo access:
#
#      git clone https://github.com/DavidMGilbert/dronedingo.git
#      cd dronedingo && sudo bash deploy/install.sh
#
#  (The curl one-liner below only works once the repo is public or the script is
#  served from your own host.)
#      curl -fsSL https://raw.githubusercontent.com/DavidMGilbert/dronedingo/main/deploy/install.sh | sudo bash
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

NM_SWITCHED=0        # set when we change the network backend (needs a reboot)

# Migrate the current Wi-Fi (from wpa_supplicant) into a NetworkManager keyfile
# so the Pi reconnects after the switch. Best-effort; skipped if no plaintext PSK.
seed_nm_wifi() {
  local conf=/etc/wpa_supplicant/wpa_supplicant.conf
  [[ -f "$conf" ]] || return 0
  local ssid psk
  ssid="$(grep -oP '(?<=ssid=")[^"]+' "$conf" | head -1 || true)"
  psk="$(grep -oP '(?<=psk=")[^"]+' "$conf" | head -1 || true)"
  [[ -z "$ssid" || -z "$psk" ]] && return 0
  local dir=/etc/NetworkManager/system-connections
  mkdir -p "$dir"
  cat > "$dir/$ssid.nmconnection" <<NMCON
[connection]
id=$ssid
type=wifi
autoconnect=true
[wifi]
mode=infrastructure
ssid=$ssid
[wifi-security]
key-mgmt=wpa-psk
psk=$psk
[ipv4]
method=auto
[ipv6]
method=auto
NMCON
  chmod 600 "$dir/$ssid.nmconnection"
  echo "  • Seeded NetworkManager profile for Wi-Fi '$ssid'."
}

# Switch the Pi to NetworkManager so the admin Network tab can manage Wi-Fi/eth.
# The change takes effect on the NEXT REBOOT, so the running session is never
# dropped mid-install.
ensure_networkmanager() {
  if systemctl is-active --quiet NetworkManager; then
    echo "  • NetworkManager already active — no change."
    return 0
  fi
  # Preserve the current Wi-Fi across the switch.
  seed_nm_wifi
  # Preferred: raspi-config's own migration (do_netconf 1 = NetworkManager).
  if command -v raspi-config >/dev/null 2>&1 \
       && raspi-config nonint do_netconf 1 >>"$LOG" 2>&1; then
    echo "  • Switched to NetworkManager via raspi-config."
  else
    # Manual fallback.
    run systemctl unmask NetworkManager || true
    run systemctl enable NetworkManager || true
    run systemctl disable dhcpcd || true       # not --now: don't drop the link
    echo "  • Enabled NetworkManager (manual)."
  fi
  NM_SWITCHED=1
}

export DEBIAN_FRONTEND=noninteractive

step "Installing system components…"
run apt-get update -qq
# Core runtime + RTL-SDR library/tools + wifi tooling. Quiet, unattended.
# network-manager powers the Wi-Fi/ethernet admin tab. vcgencmd (throttle
# status) ships with Raspberry Pi OS already, so it is not installed here.
run apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip git rsync unzip \
    librtlsdr0 rtl-sdr usbutils iw network-manager

# Ensure the DVB kernel driver doesn't grab the RTL-SDR (standard SDR setup).
if [[ ! -f /etc/modprobe.d/dronedingo-rtlsdr.conf ]]; then
  echo "blacklist dvb_usb_rtl28xxu" > /etc/modprobe.d/dronedingo-rtlsdr.conf
  run modprobe -r dvb_usb_rtl28xxu || true
fi

step "Configuring network management…"
# Switch to NetworkManager so the dashboard can manage Wi-Fi/ethernet. Effect
# is deferred to reboot, so this never drops the connection during install.
ensure_networkmanager

step "Placing application in $APP_DIR…"
id -u "$SERVICE_USER" &>/dev/null || run useradd -r -m -s /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$APP_DIR"
# If piped from curl (no local repo), clone; otherwise copy the working tree.
# ${BASH_SOURCE[0]:-} is empty when the script has no on-disk path (piped/stdin),
# which must not trip `set -u`; an empty SRC_DIR just selects the clone branch.
SELF="${BASH_SOURCE[0]:-}"
SRC_DIR="$([[ -n "$SELF" ]] && cd "$(dirname "$SELF")/.." 2>/dev/null && pwd || true)"
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

step "Configuring admin login…"
# Set the admin email + password now. Priority: environment vars (for automated
# provisioning) -> interactive prompt -> defer to first web visit.
set_admin_creds() {
  DD_E="$1" DD_P="$2" DD_APP="$APP_DIR" "$APP_DIR/.venv/bin/python" - >>"$LOG" 2>&1 <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["DD_APP"], "backend"))
from app import auth
auth.set_credentials(os.environ["DD_E"], os.environ["DD_P"])
PYEOF
}
if [[ -n "${DRONEDINGO_ADMIN_EMAIL:-}" && -n "${DRONEDINGO_ADMIN_PASSWORD:-}" ]]; then
  if set_admin_creds "$DRONEDINGO_ADMIN_EMAIL" "$DRONEDINGO_ADMIN_PASSWORD"; then
    step "  • Admin login set from environment ($DRONEDINGO_ADMIN_EMAIL)."
  else
    step "  • Env credentials rejected — set them on first web visit."
  fi
elif [[ -t 0 ]]; then
  read -rp  "    Admin email: " _ADMIN_EMAIL
  read -rsp "    Admin password (min 8 chars): " _ADMIN_PASS; echo
  if [[ -n "$_ADMIN_EMAIL" && -n "$_ADMIN_PASS" ]] \
       && set_admin_creds "$_ADMIN_EMAIL" "$_ADMIN_PASS"; then
    step "  • Admin login set."
  else
    step "  • Skipped — set the admin login on first web visit."
  fi
  unset _ADMIN_PASS
else
  step "  • No credentials given — you'll set the admin login on first web visit."
fi

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

if [[ "$NM_SWITCHED" == "1" ]]; then
  cat <<EOF
  ⚠  Network management was switched to NetworkManager.
     REBOOT to finish the switch:  sudo reboot
     (If this Pi joins over Wi-Fi, we pre-loaded its network so it should
      reconnect automatically. If it doesn't come back, reconnect it and set
      Wi-Fi from the dashboard's Settings → Network tab.)

EOF
fi
