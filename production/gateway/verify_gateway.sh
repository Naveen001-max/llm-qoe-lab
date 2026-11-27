#!/usr/bin/env bash
set -euo pipefail
: "${LAN_IF:?Set LAN_IF}"
: "${WAN_IF:?Set WAN_IF}"
echo "== Links and addresses =="; ip -br link; ip -br addr
echo "== Routes =="; ip route
echo "== Forwarding =="; sysctl net.ipv4.ip_forward
echo "== Firewall =="; nft list ruleset
echo "== NTP =="; chronyc tracking; chronyc sources -v
echo "== qdisc =="; tc -s qdisc show dev "$WAN_IF"; tc -s qdisc show dev ifb0
echo "== IFB ingress redirect =="; tc filter show dev "$WAN_IF" parent ffff:
echo "== Services =="
systemctl is-active nftables chrony
if [[ "$(sysctl -n net.ipv4.ip_forward)" != "1" ]]; then echo "FAIL: forwarding disabled"; exit 1; fi
if ! tc qdisc show dev "$WAN_IF" | grep -q netem; then echo "WARN: WAN netem qdisc missing; apply baseline profile"; fi
if ! tc qdisc show dev ifb0 | grep -q netem; then echo "WARN: IFB netem qdisc missing; apply baseline profile"; fi
echo "Gateway local checks complete. This does not by itself prove every client route; run the packet-path test from each client."
