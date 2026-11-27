#!/usr/bin/env bash
set -euo pipefail
ENV_FILE="${1:-inference/.env.inference}"
IMAGE_TAG="vllm/vllm-openai:v0.34.0"
docker pull "$IMAGE_TAG"
DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE_TAG")"
[[ "$DIGEST" == vllm/vllm-openai@sha256:* ]] || { echo "Could not resolve immutable image digest"; exit 1; }
SHA="${DIGEST#*@}"
if grep -q '^VLLM_IMAGE=' "$ENV_FILE"; then
  sed -i "s|^VLLM_IMAGE=.*|VLLM_IMAGE=${DIGEST}|" "$ENV_FILE"
else
  printf '\\nVLLM_IMAGE=%s\\n' "$DIGEST" >> "$ENV_FILE"
fi
echo "Pinned image: $DIGEST"
echo "Copy VLLM_IMAGE_DIGEST=${SHA} into production/.env.production"
