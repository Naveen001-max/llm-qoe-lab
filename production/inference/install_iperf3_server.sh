#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
apt-get update && apt-get install -y iperf3
id iperf3 >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin iperf3
cp "$(dirname "$0")/iperf3-server.service" /etc/systemd/system/qoe-iperf3-server.service
systemctl daemon-reload
systemctl enable --now qoe-iperf3-server
echo "Restrict TCP/UDP 5201 to the experiment subnet at the inference host firewall."
