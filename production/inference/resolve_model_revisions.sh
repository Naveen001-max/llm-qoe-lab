#!/usr/bin/env bash
set -euo pipefail
: "${HF_TOKEN:?Set HF_TOKEN with access to any gated model repository}"
: "${LLM_MODEL_ID:?Set LLM_MODEL_ID}"
: "${SLM_MODEL_ID:?Set SLM_MODEL_ID}"
command -v curl >/dev/null; command -v jq >/dev/null
resolve() {
  local repo="$1"
  curl -fsSL -H "Authorization: Bearer ${HF_TOKEN}" "https://huggingface.co/api/models/${repo}" | jq -r '.sha'
}
LLM_SHA="$(resolve "$LLM_MODEL_ID")"
SLM_SHA="$(resolve "$SLM_MODEL_ID")"
[[ "$LLM_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not resolve immutable LLM commit SHA"; exit 1; }
[[ "$SLM_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not resolve immutable SLM commit SHA"; exit 1; }
echo "LLM_MODEL_REVISION=$LLM_SHA"
echo "SLM_MODEL_REVISION=$SLM_SHA"
echo "Copy these exact values into both inference/.env.inference and .env.production."
