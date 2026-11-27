#!/usr/bin/env bash
set -euo pipefail
: "${API_URL:?Set API_URL, e.g. http://127.0.0.1:8088}"
echo "== Web entrypoint =="; curl -fsSI "$API_URL/"
echo "== API readiness =="; curl -fsS "$API_URL/health/ready"
echo
echo "== Model service endpoints (from API host) =="
: "${LLM_URL:?Set LLM_URL}"; : "${SLM_URL:?Set SLM_URL}"
curl -fsS "$LLM_URL/models" | python3 -m json.tool
curl -fsS "$SLM_URL/models" | python3 -m json.tool
echo "== Deployment health checks completed. Run the separate gateway client-path and calibration checks."
