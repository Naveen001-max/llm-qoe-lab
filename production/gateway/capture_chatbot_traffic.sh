#!/usr/bin/env bash
set -euo pipefail
: "${WAN_IF:?Set WAN_IF}"
: "${LAN_IF:?Set LAN_IF}"
TARGET="${1:?Usage: capture_chatbot_traffic.sh <inference-host-ip> [port]}"
PORT="${2:-8000}"
OUT="${CAPTURE_DIR:-/var/log/qoe-captures}"
mkdir -p "$OUT"; chmod 700 "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DURATION="${CAPTURE_SECONDS:-120}"
FILTER="host $TARGET and tcp port $PORT"
FIELDS=(-T fields -e frame.time_epoch -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport -e tcp.len -e tcp.analysis.retransmission -e tcp.analysis.lost_segment -E header=y -E separator=,)
echo "Capturing flow metadata simultaneously on LAN=$LAN_IF and WAN=$WAN_IF for $TARGET:$PORT."
echo "No packet payload is written. Ctrl-C stops both captures."
timeout "$DURATION" tshark -i "$LAN_IF" -f "$FILTER" "${FIELDS[@]}" > "$OUT/${STAMP}-lan-flow.csv" &
LAN_PID=$!
timeout "$DURATION" tshark -i "$WAN_IF" -f "$FILTER" "${FIELDS[@]}" > "$OUT/${STAMP}-wan-flow.csv" &
WAN_PID=$!
trap 'kill "$LAN_PID" "$WAN_PID" 2>/dev/null || true' INT TERM
wait "$LAN_PID" || true
wait "$WAN_PID" || true
echo "Saved:"
echo "  $OUT/${STAMP}-lan-flow.csv"
echo "  $OUT/${STAMP}-wan-flow.csv"
