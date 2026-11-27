#!/usr/bin/env bash
set -euo pipefail
: "${GATEWAY_NTP_IP:?Set GATEWAY_NTP_IP, e.g. 10.20.0.1}"
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
apt-get update && apt-get install -y chrony
cp -a /etc/chrony/chrony.conf "/etc/chrony/chrony.conf.backup.$(date -u +%Y%m%dT%H%M%SZ)"
cat > /etc/chrony/conf.d/llm-qoe-lab.conf <<EOF
server ${GATEWAY_NTP_IP} iburst prefer
makestep 0.1 3
rtcsync
EOF
systemctl restart chrony
sleep 2
chronyc sources -v
chronyc tracking
