# Metric dictionary and measurement boundaries

| Metric | Measurement point | Definition / caution |
|---|---|---|
| Client TTFT | Participant browser | Send action to first rendered model text; includes network, server queue, prefill and browser path. |
| vLLM TTFT | Inference engine | Engine-side time-to-first-output metric; not identical to browser TTFT. |
| Queue time | API admission | Time waiting for the serialized gateway/network-profile slot. vLLM scheduler queue time is separately available from vLLM metrics. |
| ITL | Stream receiver | Time between consecutive SSE output events. It is token-level ITL only if each event carries exactly one token. |
| TPOT | Request-level | `(E2E - TTFT) / (output_tokens - 1)` when authoritative output token usage exists and tokens > 1. |
| E2E | Browser / API | Request submit to stream completion. Keep browser-observed and server-observed values separately. |
| Throughput | Network measurement | iPerf3/perfSONAR achieved rate; do not substitute configured HTB cap. |
| Packet loss | Gateway qdisc / capture | qdisc drops and observed transport retransmissions are different observations. |
| RTT variation | Probe | Probe RTT variation is not packet-level jitter. |
| Packet jitter | Packet capture | Requires timestamped packet/inter-arrival analysis on a known flow and clock-quality metadata. |

vLLM exposes Prometheus histograms for TTFT, inter-token latency, request TPOT, queue time and E2E latency. Keep server-side metrics separate from client-observed metrics; measurement boundaries differ.
