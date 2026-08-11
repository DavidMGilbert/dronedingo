#!/usr/bin/env bash
# Put a WiFi adapter into monitor mode for Remote ID capture.
# Usage:  sudo bash deploy/monitor-mode.sh wlan1
set -euo pipefail
IFACE="${1:-wlan1}"

echo "Setting $IFACE to monitor mode…"
ip link set "$IFACE" down
iw dev "$IFACE" set type monitor
ip link set "$IFACE" up
echo "Done:"
iw dev "$IFACE" info | sed 's/^/  /'
echo
echo "Set sources.wifi_remoteid.enabled: true and interface: $IFACE in"
echo "config/skywarden.yaml, then restart: sudo systemctl restart skywarden"
