#!/usr/bin/env bash
set -euo pipefail
: "${TARGET_IP:?Set TARGET_IP to the next chatbot hop}"
: "${EXPECTED_NEXT_HOP:?Set EXPECTED_NEXT_HOP to the gateway address on this host's subnet}"
ip route
echo "== Route to $TARGET_IP =="
ROUTE="$(ip route get "$TARGET_IP")"
echo "$ROUTE"
NEXT="$(awk '{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1);exit}}' <<<"$ROUTE")"
if [[ "$NEXT" != "$EXPECTED_NEXT_HOP" ]]; then
  echo "FAIL: next-hop '$NEXT' is not the required gateway '$EXPECTED_NEXT_HOP'"
  exit 1
fi
echo "PASS: route uses the required gateway"
if [[ -n "${PROBE_URL:-}" ]]; then
  curl --connect-timeout 5 --max-time 15 -fsS "$PROBE_URL" >/dev/null
  echo "PASS: endpoint probe succeeded"
fi
