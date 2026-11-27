#!/usr/bin/env bash
set -euo pipefail
: "${LLM_URL:?Set LLM_URL}"; : "${SLM_URL:?Set SLM_URL}"
: "${LLM_API_KEY:?Set LLM_API_KEY}"; : "${SLM_API_KEY:?Set SLM_API_KEY}"
: "${INFERENCE_CA:?Set INFERENCE_CA}"
check_one() {
  local name="$1" url="$2" key="$3"
  echo "== $name /v1/models =="
  curl --cacert "$INFERENCE_CA" -H "Authorization: Bearer $key" -fsS "$url/models" | python3 -m json.tool
  echo "== $name metrics =="
  local base="${url%/v1}"
  curl --cacert "$INFERENCE_CA" -fsS "$base/metrics" | grep -E 'vllm:(time_to_first_token|inter_token_latency|request_time_per_output_token|request_queue_time|e2e_request_latency)' | head -30
}
check_one llm "$LLM_URL" "$LLM_API_KEY"
check_one slm "$SLM_URL" "$SLM_API_KEY"
