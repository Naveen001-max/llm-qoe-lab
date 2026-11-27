#!/usr/bin/env bash
set -euo pipefail
: "${HOST_ROLE:?Set HOST_ROLE=api, emulator or inference}"
: "${HOST_IF:?Set HOST_IF to the host NIC}"
: "${HOST_CIDR:?Set HOST_CIDR, e.g. 10.20.0.10/24}"
: "${DEFAULT_GW:?Set DEFAULT_GW}"
: "${GATEWAY_NTP_IP:?Set the gateway IP on this host subnet}"
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
case "$HOST_ROLE" in api|emulator|inference) ;; *) echo "Unknown HOST_ROLE"; exit 2;; esac
ip link show "$HOST_IF" >/dev/null
echo "This configures static IPv4 on $HOST_IF for role=$HOST_ROLE."
echo "Keep local console access; network may restart."
read -r -p "Type CONFIGURE-LAB-HOST to continue: " c
[[ "$c" == "CONFIGURE-LAB-HOST" ]] || exit 1
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  iproute2 chrony wireshark wireshark-common tshark iperf3 tcpdump ethtool \
  traceroute curl jq python3 python3-venv ca-certificates
if [[ "$HOST_ROLE" != "emulator" ]]; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
  systemctl enable --now docker
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/root/qoe-host-backup-${STAMP}"
mkdir -p "$BACKUP/netplan"
cp -a /etc/netplan/. "$BACKUP/netplan/" 2>/dev/null || true
for old in /etc/netplan/*.yaml; do
  [[ -f "$old" ]] || continue
  [[ "$(basename "$old")" == "99-qoe-lab-host.yaml" ]] && continue
  mv "$old" "$BACKUP/netplan/"
done
if [[ -d /etc/cloud/cloud.cfg.d ]]; then
  cp -a /etc/cloud/cloud.cfg.d "$BACKUP/cloud.cfg.d" 2>/dev/null || true
  printf 'network: {config: disabled}\n' > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
fi
ROUTES_BLOCK="        - to: default
          via: ${DEFAULT_GW}"
if [[ -n "${LAB_ROUTE_CIDR:-}" || -n "${LAB_ROUTE_GW:-}" ]]; then
  : "${LAB_ROUTE_CIDR:?Set both LAB_ROUTE_CIDR and LAB_ROUTE_GW}"
  : "${LAB_ROUTE_GW:?Set both LAB_ROUTE_CIDR and LAB_ROUTE_GW}"
  ROUTES_BLOCK="${ROUTES_BLOCK}
        - to: ${LAB_ROUTE_CIDR}
          via: ${LAB_ROUTE_GW}"
fi
cat > /etc/netplan/99-qoe-lab-host.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${HOST_IF}:
      dhcp4: false
      addresses: [${HOST_CIDR}]
      routes:
${ROUTES_BLOCK}
      nameservers:
        addresses: [${DNS_SERVERS:-1.1.1.1, 9.9.9.9}]
      optional: true
EOF
chmod 600 /etc/netplan/99-qoe-lab-host.yaml
cat > /etc/sysctl.d/99-qoe-lab-ipv6.conf <<EOF
net.ipv6.conf.${HOST_IF}.disable_ipv6=1
EOF
sysctl --system >/dev/null
cat > /etc/chrony/conf.d/llm-qoe-lab.conf <<EOF
server ${GATEWAY_NTP_IP} iburst prefer
makestep 0.1 3
rtcsync
EOF
systemctl enable --now chrony
netplan generate
netplan try --timeout 120
systemctl restart chrony
echo "Host configured. Backup: $BACKUP"
echo "Verify route and clock:"
ip -br addr
ip route
chronyc tracking
chronyc sources -v
if [[ "$HOST_ROLE" == "inference" ]]; then
  echo "Install NVIDIA driver + NVIDIA Container Toolkit according to the GPU/Ubuntu compatibility matrix."
  echo "Then run nvidia-smi and docker run --rm --gpus all <matching CUDA image> nvidia-smi."
fi
