#!/usr/bin/env bash
set -euo pipefail
: "${LAN_IF:?Set LAN_IF to the physical experiment-side NIC}"
: "${WAN_IF:?Set WAN_IF to the physical upstream-side NIC}"
: "${LAN_CIDR:?Set LAN_CIDR, e.g. 10.20.0.1/24}"
: "${LAN_GW_IP:?Set LAN_GW_IP, e.g. 10.20.0.1}"
: "${NTP_ALLOW_CIDRS:?Set comma/space-separated trusted LAN and inference subnets for chrony}"
: "${WAN_DHCP4:?Set WAN_DHCP4=true or false}"
: "${API_HOST_IP:?Set API_HOST_IP to the fixed address of the API server}"
: "${INFERENCE_IPS:?Set space/comma-separated inference server IPv4 addresses}"
WAN_DHCP4="${WAN_DHCP4:-true}"
if [[ "$LAN_IF" == "$WAN_IF" ]]; then echo "LAN_IF and WAN_IF must be different"; exit 2; fi
python3 - "$LAN_CIDR" "$LAN_GW_IP" <<'PY'
import ipaddress,sys
if ipaddress.ip_interface(sys.argv[1]).ip != ipaddress.ip_address(sys.argv[2]):
    raise SystemExit("LAN_GW_IP must equal the host address in LAN_CIDR")
PY
INFERENCE_SET="$(echo "$INFERENCE_IPS" | tr ',' ' ')"
INFERENCE_RULES=""
for target in $INFERENCE_SET; do
  python3 - "$target" <<'PY'
import ipaddress,sys
ipaddress.IPv4Address(sys.argv[1])
PY
  # API host on WAN may call only the approved inference/iPerf ports on LAN.
  INFERENCE_RULES+="    iifname \"${WAN_IF}\" oifname \"${LAN_IF}\" ip saddr ${API_HOST_IP} ip daddr ${target} tcp dport { 8001, 8002, 5201 } accept
"
  # Inference hosts may download model artifacts through the gateway; restrict to web/DNS.
  INFERENCE_RULES+="    iifname \"${LAN_IF}\" oifname \"${WAN_IF}\" ip saddr ${target} tcp dport { 80, 443 } accept
    iifname \"${LAN_IF}\" oifname \"${WAN_IF}\" ip saddr ${target} udp dport { 53, 123 } accept
    iifname \"${LAN_IF}\" oifname \"${WAN_IF}\" ip saddr ${target} tcp dport 53 accept
"
done
if ! ip link show "$LAN_IF" >/dev/null 2>&1 || ! ip link show "$WAN_IF" >/dev/null 2>&1; then
  echo "Configured NIC not found. Current interfaces:"; ip -br link; exit 2
fi
if [[ $EUID -ne 0 ]]; then echo "Run with sudo."; exit 2; fi
echo "This will configure routing, firewall/NAT, NTP, NetEm and network tools."
echo "LAN: $LAN_IF $LAN_CIDR  WAN: $WAN_IF  DHCP: $WAN_DHCP4"
echo "Keep local console access. Netplan may interrupt SSH."
read -r -p "Type CONFIGURE-ISOLATED-GATEWAY to continue: " confirm
[[ "$confirm" == "CONFIGURE-ISOLATED-GATEWAY" ]] || { echo "Cancelled"; exit 1; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  iproute2 iptables nftables chrony wireshark wireshark-common tshark iperf3 \
  tcpdump ethtool jq curl ca-certificates traceroute net-tools
install -d -m 0755 /etc/netplan /etc/nftables.d /etc/sysctl.d
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/root/qoe-gateway-backup-$STAMP"
mkdir -p "$BACKUP/netplan"
cp -a /etc/netplan/. "$BACKUP/netplan/" 2>/dev/null || true
cp -a /etc/chrony/chrony.conf "$BACKUP/chrony.conf" 2>/dev/null || true
# This installer is for a dedicated lab gateway: archive and disable prior Netplan YAMLs.
for old in /etc/netplan/*.yaml; do
  [[ -f "$old" ]] || continue
  [[ "$(basename "$old")" == "99-qoe-gateway.yaml" ]] && continue
  mv "$old" "$BACKUP/netplan/"
done
if [[ -d /etc/cloud/cloud.cfg.d ]]; then
  cp -a /etc/cloud/cloud.cfg.d "$BACKUP/cloud.cfg.d" 2>/dev/null || true
  printf 'network: {config: disabled}\n' > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
fi
if [[ "$WAN_DHCP4" == "true" ]]; then
  WAN_BLOCK="      dhcp4: true
      optional: true"
else
  : "${WAN_CIDR:?Set WAN_CIDR for static WAN}"
  : "${WAN_GW:?Set WAN_GW for static WAN default route}"
  WAN_DNS="${WAN_DNS:-1.1.1.1, 9.9.9.9}"
  WAN_BLOCK="      dhcp4: false
      addresses: [${WAN_CIDR}]
      routes:
        - to: default
          via: ${WAN_GW}
      nameservers:
        addresses: [${WAN_DNS}]
      optional: true"
fi
cat > /etc/netplan/99-qoe-gateway.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${LAN_IF}:
      dhcp4: false
      addresses: [${LAN_CIDR}]
      optional: true
    ${WAN_IF}:
$(printf '%s\n' "$WAN_BLOCK")
EOF
chmod 600 /etc/netplan/99-qoe-gateway.yaml
cat > /etc/sysctl.d/99-qoe-gateway.conf <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.${LAN_IF}.rp_filter=0
net.ipv4.conf.${WAN_IF}.rp_filter=0
EOF
sysctl --system
LAN_NET="$(python3 - "$LAN_CIDR" <<'PY'
import ipaddress,sys
print(ipaddress.ip_interface(sys.argv[1]).network)
PY
)"
NTP_NETS="$(echo "$NTP_ALLOW_CIDRS" | tr ',' ' ')"
NTP_SET="$(echo "$NTP_NETS" | tr ' ' ',')"

cat > /etc/nftables.conf <<EOF
#!/usr/sbin/nft -f
flush ruleset
table inet qoe_filter {
  chain input {
    type filter hook input priority filter; policy drop;
    iifname "lo" accept
    ct state established,related accept
    ip protocol icmp accept
    iifname "${LAN_IF}" udp dport 123 accept
    iifname "${WAN_IF}" ip saddr { ${NTP_SET} } udp dport 123 accept
    iifname "${LAN_IF}" tcp dport 22 accept
    iifname "${WAN_IF}" ip saddr ${API_HOST_IP} tcp dport 8090 accept
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
    ct state established,related accept
    iifname "${LAN_IF}" oifname "${WAN_IF}" ip saddr ${LAN_NET} ip daddr ${API_HOST_IP} tcp dport { 80, 443 } accept
    iifname "${LAN_IF}" oifname "${WAN_IF}" ip saddr ${LAN_NET} udp dport 53 accept
    iifname "${LAN_IF}" oifname "${WAN_IF}" ip saddr ${LAN_NET} tcp dport 53 accept
$(printf '%s' "$INFERENCE_RULES")
  }
  chain output { type filter hook output priority filter; policy accept; }
}
table ip qoe_nat {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "${WAN_IF}" ip saddr ${LAN_NET} masquerade
  }
}
EOF
nft -c -f /etc/nftables.conf
systemctl enable --now nftables
nft -f /etc/nftables.conf
# NTP server on the isolated LAN and inference subnet.
for subnet in $NTP_NETS; do
  if ! grep -Fqx "allow ${subnet}" /etc/chrony/chrony.conf; then
    printf '\n# LLM QoE Lab trusted experiment subnet\nallow %s\n' "$subnet" >> /etc/chrony/chrony.conf
  fi
done
systemctl enable --now chrony
modprobe ifb numifbs=1 || true
ip link add ifb0 type ifb 2>/dev/null || true
ip link set ifb0 up
echo "Netplan configuration prepared. Applying with 120-second rollback confirmation."
netplan generate
netplan try --timeout 120
systemctl restart nftables chrony
echo "Gateway software installed. Verify from local console before connecting participants."
echo "Backup: $BACKUP"
ip -br addr
nft list ruleset
chronyc tracking
