#!/usr/bin/env bash
set -euo pipefail
: "${WAN_IF:?Set WAN_IF}"
: "${QOE_GATEWAY_TOKEN:?Set a long random QOE_GATEWAY_TOKEN}"
: "${GATEWAY_TLS_CERT:?Set TLS server certificate path}"
: "${GATEWAY_TLS_KEY:?Set TLS server private key path}"
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
install -d -m 0750 /opt/qoe-gateway /etc/qoe-gateway
cp "$(dirname "$0")/agent.py" /opt/qoe-gateway/agent.py
python3 -m venv /opt/qoe-gateway/venv
/opt/qoe-gateway/venv/bin/pip install --upgrade pip && /opt/qoe-gateway/venv/bin/pip install fastapi==0.115.12 uvicorn==0.34.0
install -m 0644 "$GATEWAY_TLS_CERT" /etc/qoe-gateway/gateway.crt
install -m 0600 "$GATEWAY_TLS_KEY" /etc/qoe-gateway/gateway.key
cat > /etc/qoe-gateway/agent.env <<EOF
WAN_IF=${WAN_IF}
QOE_GATEWAY_TOKEN=${QOE_GATEWAY_TOKEN}
GATEWAY_TLS_CERT=/etc/qoe-gateway/gateway.crt
GATEWAY_TLS_KEY=/etc/qoe-gateway/gateway.key
EOF
chmod 600 /etc/qoe-gateway/agent.env
cp "$(dirname "$0")/qoe-gateway-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now qoe-gateway-agent
echo "Agent installed. Restrict TCP/8090 to the API host in nftables/firewall."
