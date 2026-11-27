#!/usr/bin/env bash
set -euo pipefail
: "${WAN_IF:?Set WAN_IF}"
LATENCY_MS="${LATENCY_MS:-0}"
JITTER_MS="${JITTER_MS:-0}"
LOSS_PCT="${LOSS_PCT:-0}"
BANDWIDTH_MBIT="${BANDWIDTH_MBIT:-0}"
for pair in "LATENCY_MS:$LATENCY_MS:0:2000" "JITTER_MS:$JITTER_MS:0:500" "LOSS_PCT:$LOSS_PCT:0:30" "BANDWIDTH_MBIT:$BANDWIDTH_MBIT:0:1000"; do
  IFS=: read -r name value min max <<<"$pair"
  awk -v v="$value" -v lo="$min" -v hi="$max" 'BEGIN{exit !(v>=lo && v<=hi)}' || { echo "$name out of range"; exit 2; }
done
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 2; }
modprobe ifb numifbs=1
ip link add ifb0 type ifb 2>/dev/null || true
ip link set ifb0 up
tc qdisc replace dev "$WAN_IF" handle ffff: ingress
tc filter replace dev "$WAN_IF" parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev ifb0
apply_one(){
  local dev="$1"
  tc qdisc del dev "$dev" root 2>/dev/null || true
  local args=(delay "${LATENCY_MS}ms")
  if [[ "$JITTER_MS" != "0" ]]; then args+=("${JITTER_MS}ms" distribution normal); fi
  if [[ "$LOSS_PCT" != "0" ]]; then args+=(loss random "${LOSS_PCT}%"); fi
  if [[ "$BANDWIDTH_MBIT" != "0" ]]; then
    tc qdisc replace dev "$dev" root handle 1: htb default 10
    tc class replace dev "$dev" parent 1: classid 1:10 htb rate "${BANDWIDTH_MBIT}mbit" ceil "${BANDWIDTH_MBIT}mbit"
    tc qdisc replace dev "$dev" parent 1:10 handle 10: netem "${args[@]}"
  else
    tc qdisc replace dev "$dev" root netem "${args[@]}"
  fi
}
apply_one "$WAN_IF"
apply_one ifb0
echo "Applied one-way delay/jitter/loss and rate cap on WAN egress and IFB ingress."
tc -s qdisc show dev "$WAN_IF"
tc -s qdisc show dev ifb0
tc -s class show dev "$WAN_IF" || true
