#!/usr/bin/env bash
# LLM QoE Lab - consolidated acceptance test
# Run from any directory: bash production/run_full_validation.sh
# Safe defaults: isolated network namespace for NetEm; no production qdisc changes.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD="$ROOT/production"
WEB="$PROD/web"
REPORT_DIR="$ROOT/test-reports"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/full-validation-$STAMP.txt"
mkdir -p "$REPORT_DIR"
PASS=0; FAIL=0; SKIP=0
declare -a RESULTS=()

log(){ printf '%s\n' "$*" | tee -a "$REPORT"; }
run_step(){
  local name="$1"; shift
  log "\n===== $name ====="
  if "$@" 2>&1 | tee -a "$REPORT"; then
    PASS=$((PASS+1)); RESULTS+=("PASS | $name")
  else
    FAIL=$((FAIL+1)); RESULTS+=("FAIL | $name")
  fi
}
skip_step(){
  SKIP=$((SKIP+1)); RESULTS+=("SKIP | $1")
  log "\n===== SKIP: $1 =====\n$2"
}
has(){ command -v "$1" >/dev/null 2>&1; }

log "LLM QoE Lab consolidated validation"
log "UTC: $STAMP"
log "Project: $ROOT"
log "Host: $(uname -a)"
log "This script does not change the host's production network qdiscs."

# 1. Frontend production build
if has node && has npm; then
  run_step "React/TypeScript clean dependency install and production build" bash -c \
    'cd "$1" && npm ci --no-audit --no-fund && npm run build' _ "$WEB"
else
  skip_step "React production build" "Node.js and npm are required."
fi

# 2. Docker build, startup, PostgreSQL, Redis and API readiness
COMPOSE=(docker compose --env-file .env.production -f docker-compose.yml)
if has docker && docker compose version >/dev/null 2>&1; then
  if [[ -f "$PROD/.env.production" ]]; then
    run_step "Docker Compose configuration validation" bash -c \
      'cd "$1" && docker compose --env-file .env.production -f docker-compose.yml config --quiet' _ "$PROD"
    run_step "Docker image build (API and React web)" bash -c \
      'cd "$1" && docker compose --env-file .env.production -f docker-compose.yml build api web' _ "$PROD"
    run_step "Start PostgreSQL, Redis, API and web services" bash -c \
      'cd "$1" && docker compose --env-file .env.production -f docker-compose.yml up -d postgres redis api web caddy prometheus grafana' _ "$PROD"
    run_step "PostgreSQL readiness and SQL round-trip" bash -c '
      cd "$1"
      docker compose --env-file .env.production -f docker-compose.yml exec -T postgres sh -lc \
        '\''pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" &&
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT 1"'\'' | grep -q 1
    ' _ "$PROD"
    run_step "Redis PING and SET/GET round-trip" bash -c '
      cd "$1"
      docker compose --env-file .env.production -f docker-compose.yml exec -T redis sh -lc \
        '\''redis-cli PING && redis-cli SET qoe_validation_probe ok EX 30 && redis-cli GET qoe_validation_probe'\'' |
        grep -q ok
    ' _ "$PROD"
    run_step "Production API readiness endpoint" bash -c '
      cd "$1"
      for i in $(seq 1 30); do
        if docker compose --env-file .env.production -f docker-compose.yml exec -T api \
          python -c '\''import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health/ready",timeout=3).status)'\'' 2>/dev/null | grep -q 200; then exit 0; fi
        sleep 3
      done
      docker compose --env-file .env.production -f docker-compose.yml ps
      exit 1
    ' _ "$PROD"
    run_step "Docker service health summary" bash -c '
      cd "$1"
      docker compose --env-file .env.production -f docker-compose.yml ps
      docker compose --env-file .env.production -f docker-compose.yml ps --format json |
        python3 -c '\''import json,sys; s=sys.stdin.read().strip(); a=json.loads(s) if s.startswith("[") else [json.loads(x) for x in s.splitlines() if x.strip()]; bad=[x for x in a if x.get("State")!="running" or (x.get("Health") and x.get("Health")!="healthy")]; print("Services:",len(a),"unhealthy:",len(bad)); [print(x.get("Name"),x.get("State"),x.get("Health")) for x in a]; sys.exit(bool(bad))'\''
    ' _ "$PROD"
  else
    skip_step "Docker build/startup + PostgreSQL/Redis integration" \
      "Missing production/.env.production. Create it from production/.env.production.example and fill real local values."
  fi
else
  skip_step "Docker build/startup + PostgreSQL/Redis integration" \
    "Docker Engine and the Docker Compose plugin must be installed and accessible to this user."
fi

# 3. Live Groq and Gemini provider checks. Tests provider endpoints directly,
# using secrets from root .env or production/.env.production; never prints keys.
run_provider_tests(){
python3 - "$ROOT" <<'PY'
import os, sys, json, urllib.request, urllib.error
from pathlib import Path
root=Path(sys.argv[1])
def envfile(path):
    d={}
    if not path.exists(): return d
    for line in path.read_text(errors="ignore").splitlines():
        s=line.strip()
        if not s or s.startswith("#") or "=" not in s: continue
        k,v=s.split("=",1); d[k.strip()]=v.strip().strip('"').strip("'")
    return d
e={}
for f in (root/".env", root/"production/.env.production"):
    e.update(envfile(f))
def request(url, payload, headers=None):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json",**(headers or {})},method="POST")
    with urllib.request.urlopen(req,timeout=45) as r: return r.status, r.read().decode(errors="replace")
tested=0; errors=[]
groq=e.get("GROQ_API_KEY")
if groq and not groq.lower().startswith("your_"):
    model=e.get("GROQ_MODEL","openai/gpt-oss-20b")
    base=e.get("GROQ_BASE_URL","https://api.groq.com/openai/v1").rstrip("/")
    try:
        code,body=request(base+"/chat/completions",{"model":model,"messages":[{"role":"user","content":"Reply with exactly: QOE_TEST_OK"}],"max_tokens":12,"temperature":0},{"Authorization":"Bearer "+groq})
        obj=json.loads(body); text=obj.get("choices",[{}])[0].get("message",{}).get("content","")
        if code==200 and text: print(f"PASS Groq live inference ({model}); response received"); tested+=1
        else: raise RuntimeError("empty or malformed completion")
    except Exception as ex: errors.append("Groq: "+str(ex)); print("FAIL Groq live inference:",ex)
else: print("SKIP Groq: GROQ_API_KEY missing or placeholder")
gem=e.get("GEMINI_API_KEY")
if gem and not gem.lower().startswith("your_"):
    model=e.get("GEMINI_MODEL","gemini-2.0-flash")
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gem}"
    try:
        code,body=request(url,{"contents":[{"parts":[{"text":"Reply with exactly: QOE_TEST_OK"}]}],"generationConfig":{"maxOutputTokens":12,"temperature":0}})
        obj=json.loads(body); parts=obj.get("candidates",[{}])[0].get("content",{}).get("parts",[])
        if code==200 and parts: print(f"PASS Gemini live inference ({model}); response received"); tested+=1
        else: raise RuntimeError("empty or malformed completion")
    except Exception as ex: errors.append("Gemini: "+str(ex)); print("FAIL Gemini live inference:",ex)
else: print("SKIP Gemini: GEMINI_API_KEY missing or placeholder")
if tested==0 and not errors: print("SKIP live provider tests: configure at least one real provider key")
if errors or tested != 2: print("Both Groq and Gemini must be configured and return a completion for this check to pass."); sys.exit(1)
PY
}
if has python3; then
  run_step "Live Groq/Gemini inference (configured providers)" run_provider_tests
else
  skip_step "Live Groq/Gemini inference" "python3 is required."
fi

# 4. Real tc/NetEm in an isolated Linux network namespace. Does not touch WAN_IF.
run_isolated_netem(){
  for c in ip tc ping; do command -v "$c" >/dev/null || { echo "Missing $c"; return 1; }; done
  local ns="qoe-test-$$" hostv="qoeh$$" nsv="qoen$$"
  local SUDO=()
  if [[ $EUID -ne 0 ]]; then has sudo || { echo "sudo is required for network namespaces"; return 1; }; SUDO=(sudo); fi
  cleanup(){ "${SUDO[@]}" ip netns del "$ns" >/dev/null 2>&1 || true; "${SUDO[@]}" ip link del "$hostv" >/dev/null 2>&1 || true; }
  trap cleanup RETURN
  "${SUDO[@]}" ip netns add "$ns" || return 1
  "${SUDO[@]}" ip link add "$hostv" type veth peer name "$nsv" || return 1
  "${SUDO[@]}" ip link set "$nsv" netns "$ns"
  "${SUDO[@]}" ip addr add 198.18.77.1/30 dev "$hostv"
  "${SUDO[@]}" ip link set "$hostv" up
  "${SUDO[@]}" ip netns exec "$ns" ip addr add 198.18.77.2/30 dev "$nsv"
  "${SUDO[@]}" ip netns exec "$ns" ip link set lo up
  "${SUDO[@]}" ip netns exec "$ns" ip link set "$nsv" up
  "${SUDO[@]}" ip netns exec "$ns" tc qdisc replace dev "$nsv" root netem delay 80ms 5ms loss 0.5%
  echo "Applied isolated namespace qdisc:"
  "${SUDO[@]}" ip netns exec "$ns" tc -s qdisc show dev "$nsv"
  local ms
  ms="$("${SUDO[@]}" ip netns exec "$ns" ping -n -c 4 -W 3 198.18.77.1 2>/dev/null | awk -F'/' '/rtt|round-trip/{print $5; exit}')"
  echo "Observed ping average RTT (ms): ${ms:-unavailable}"
  [[ -n "$ms" ]] || return 1
  awk -v x="$ms" 'BEGIN{exit !(x>=60)}' || { echo "Expected injected delay was not observed"; return 1; }
  echo "PASS: isolated NetEm delay observed; host production interfaces were untouched."
}
if has ip && has tc; then
  run_step "Actual NetEm packet shaping in isolated network namespace" run_isolated_netem
else
  skip_step "Isolated NetEm packet shaping" "Linux iproute2 (ip and tc) is required. Run inside Ubuntu/WSL2."
fi

# 5. Physical-interface packet capture is opt-in and metadata-only.
# Set CAPTURE_IFACE and CAPTURE_TARGET (IP address). Capture writes pcapng
# as tshark fields CSV; no packet payload is written.
run_physical_capture(){
  has tshark || { echo "tshark is required"; return 1; }
  local SUDO=(); if [[ $EUID -ne 0 ]]; then has sudo || { echo "sudo is required for capture"; return 1; }; SUDO=(sudo); fi
  [[ -n "${CAPTURE_IFACE:-}" && -n "${CAPTURE_TARGET:-}" ]] || return 2
  local out="$REPORT_DIR/physical-capture-$STAMP.csv"
  echo "Capturing metadata only on $CAPTURE_IFACE for host $CAPTURE_TARGET."
  "${SUDO[@]}" timeout "${CAPTURE_SECONDS:-15}" tshark -i "$CAPTURE_IFACE" \
    -f "host $CAPTURE_TARGET" -T fields \
    -e frame.time_epoch -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport \
    -e tcp.len -e tcp.analysis.retransmission \
    -E header=y -E separator=, > "$out" 2>"$REPORT_DIR/tshark-$STAMP.log" &
  local capture_pid=$!
  sleep 2
  ping -n -c 5 -W 2 "$CAPTURE_TARGET" >/dev/null 2>&1 || true
  wait "$capture_pid" || true
  [[ -s "$out" ]] || { echo "No capture data created: $out"; cat "$REPORT_DIR/tshark-$STAMP.log"; return 1; }
  local count
  count="$(($(wc -l < "$out")-1))"
  echo "Metadata CSV: $out"
  echo "Captured packet records: $count"
  [[ "$count" -gt 0 ]]
}
if [[ -n "${CAPTURE_IFACE:-}" && -n "${CAPTURE_TARGET:-}" ]]; then
  if has tshark; then run_step "Physical interface packet capture (metadata-limited)" run_physical_capture
  else skip_step "Physical interface packet capture" "Install tshark/Wireshark CLI first."; fi
else
  skip_step "Physical interface packet capture" \
    "Set CAPTURE_IFACE and CAPTURE_TARGET to capture a real lab interface. No interface was guessed; no traffic was captured."
fi

# Summary
log "\n================ FINAL RESULTS ================"
for item in "${RESULTS[@]}"; do log "$item"; done
log "\nPASS=$PASS FAIL=$FAIL SKIP=$SKIP"
log "Report: $REPORT"
if (( FAIL > 0 )); then
  log "RESULT: NOT READY — fix failed checks and rerun."
  exit 1
elif (( SKIP > 0 )); then
  log "RESULT: PARTIAL — skipped checks require environment configuration or privileges."
  exit 2
else
  log "RESULT: ALL AUTOMATED CHECKS PASSED."
fi
