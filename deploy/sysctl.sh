#!/usr/bin/env bash
# ============================================================================
#  DroneDingo privileged system helper.
#  Invoked ONLY via the narrow sudoers rule created by install.sh. Each verb is
#  a constrained action; there is no shell passthrough. Keep it that way.
#
#      sysctl.sh wifi-connect <ssid> <password> [iface]
#      sysctl.sh os-check
#      sysctl.sh os-upgrade
#      sysctl.sh reboot
# ============================================================================
set -euo pipefail

verb="${1:-}"; shift || true

case "$verb" in
  wifi-connect)
    ssid="${1:-}"; psk="${2:-}"; iface="${3:-}"
    [[ -z "$ssid" ]] && { echo "ssid required" >&2; exit 2; }
    if [[ -n "$iface" ]]; then
      if [[ -n "$psk" ]]; then
        nmcli dev wifi connect "$ssid" password "$psk" ifname "$iface"
      else
        nmcli dev wifi connect "$ssid" ifname "$iface"
      fi
    else
      if [[ -n "$psk" ]]; then
        nmcli dev wifi connect "$ssid" password "$psk"
      else
        nmcli dev wifi connect "$ssid"
      fi
    fi
    ;;

  os-check)
    apt-get update -qq >/dev/null 2>&1 || true
    # List upgradable packages, one per line (exclude the header line).
    apt list --upgradable 2>/dev/null | grep -v '^Listing' || true
    ;;

  os-upgrade)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get upgrade -y -qq
    apt-get autoremove -y -qq || true
    echo "OS upgrade complete."
    ;;

  reboot)
    # Give the HTTP response time to flush before the box goes down.
    ( sleep 2; systemctl reboot ) >/dev/null 2>&1 &
    echo "Rebooting."
    ;;

  *)
    echo "unknown verb: $verb" >&2
    exit 2
    ;;
esac
