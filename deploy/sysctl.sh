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

  net-dhcp)
    iface="${1:?iface required}"
    con="$(nmcli -t -g GENERAL.CONNECTION device show "$iface" 2>/dev/null || true)"
    [[ -z "$con" ]] && con="dronedingo-$iface"
    nmcli con mod "$con" ipv4.method auto ipv4.gateway "" ipv4.addresses "" \
      ipv4.dns "" 2>/dev/null || nmcli con add type ethernet ifname "$iface" con-name "$con"
    nmcli con up "$con"
    ;;

  net-static)
    iface="${1:?iface required}"; addr="${2:?addr required}"
    gw="${3:-}"; dns="${4:-}"
    con="$(nmcli -t -g GENERAL.CONNECTION device show "$iface" 2>/dev/null || true)"
    [[ -z "$con" ]] && { con="dronedingo-$iface"; nmcli con add type ethernet ifname "$iface" con-name "$con"; }
    nmcli con mod "$con" ipv4.method manual ipv4.addresses "$addr"
    [[ -n "$gw" ]]  && nmcli con mod "$con" ipv4.gateway "$gw"
    [[ -n "$dns" ]] && nmcli con mod "$con" ipv4.dns "$dns"
    nmcli con up "$con"
    ;;

  os-check)
    apt-get update -qq >/dev/null 2>&1 || true
    # List upgradable packages, one per line (exclude the header line).
    apt list --upgradable 2>/dev/null | grep -v '^Listing' || true
    ;;

  os-upgrade)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get full-upgrade -y -qq
    apt-get autoremove -y -qq || true
    echo "OS upgrade complete."
    ;;

  reboot)
    # Give the HTTP response time to flush before the box goes down.
    ( sleep 2; systemctl reboot ) >/dev/null 2>&1 &
    echo "Rebooting."
    ;;

  restart)
    # Restart just the app service (applies config changes). Detached so the
    # HTTP response flushes before the service is torn down.
    ( sleep 1; systemctl restart dronedingo ) >/dev/null 2>&1 &
    echo "Restarting DroneDingo."
    ;;

  *)
    echo "unknown verb: $verb" >&2
    exit 2
    ;;
esac
