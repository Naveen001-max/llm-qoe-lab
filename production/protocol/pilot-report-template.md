# WP5 — Calibration and Pilot Report

## 1. Environment manifest
- Study protocol version:
- Gateway hostname / Ubuntu release:
- LAN interface / WAN interface:
- API host and inference host addresses:
- Chrony tracking offset on each host:
- vLLM image digest:
- LLM repository + commit:
- SLM repository + commit:
- GPU model, VRAM, driver and CUDA compatibility:
- Container versions and configuration hashes:

## 2. Network-path validation
Attach participant-to-API and API-to-inference `ip route get` output.
Attach gateway LAN/WAN packet-capture metadata demonstrating both legs traverse the gateway.
Record any unexpected interface, route, DNS, IPv6 or firewall path.

## 3. Profile calibration
For every profile, report configured latency/jitter/loss/bandwidth, `tc -s` qdisc counters, ICMP RTT min/mean/max/mdev/loss, iPerf3 achieved throughput, and LLM/SLM request metrics.
Do not equate ICMP RTT mdev with packet-level jitter. Attach packet inter-arrival analysis from tshark separately.

## 4. Clock validation
Report chrony source, stratum, system time offset and root dispersion for gateway, API, inference and participant hosts. Define acceptable offset before the pilot.

## 5. Instrumentation validation
- Unique experiment/trace/request IDs:
- SSE first-output and completion:
- Client first-render frame:
- Chunk count and UTF-8 bytes:
- Provider token usage and finish reason:
- Participant event ledger / JSONL consistency:
- PostgreSQL export consistency:
- Questionnaire and rubric capture:

## 6. Human pilot
- Ethics approval reference:
- Pilot participants:
- Deviations / usability issues:
- Missing telemetry:
- Task clarity and completion:
- NASA-TLX / QoE questionnaire feedback:
- Corrective actions:

## 7. Go/no-go decision
List unresolved issues, owner, severity and closure evidence. Main-study recruitment must not start until ethics approval, calibration and pilot acceptance are documented.
