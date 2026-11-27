# WP5 calibration runner

Run from the API/experiment host whose route to the inference subnet crosses the Ubuntu gateway. Start the iPerf3 server on the inference-side measurement endpoint first. The gateway and inference TLS certificates should be issued by your internal CA; supply the matching CA bundles.

```bash
export GATEWAY_TOKEN='...'
export LLM_API_KEY='...'
export SLM_API_KEY='...'
python3 run_calibration.py \
  --gateway https://qoe-gateway.lab:8090 \
  --gateway-ca ../secrets/gateway-ca.crt \
  --inference-ca ../secrets/inference-ca.crt \
  --iperf-host 10.20.0.20 \
  --llm-url https://qoe-inference.lab:8001/v1 --llm-model llama-3.1-8b-instruct --llm-key "$LLM_API_KEY" \
  --slm-url https://qoe-inference.lab:8002/v1 --slm-model qwen2.5-1.5b-instruct --slm-key "$SLM_API_KEY" \
  --out calibration-results.json
```

It applies each profile, runs a 15-second iPerf3 test, sends one streamed prompt to each model, records client-observed TTFT/E2E/inter-output gaps and finish reason, then attempts to reset the gateway to baseline. Repeat runs; this is calibration, not the human pilot or a statistically powered study. Ensure the iPerf server is on the far side of the gateway so the measured flow actually traverses the shaped path.


The JSON result contains the applied gateway profile and `tc -s qdisc` status, ICMP RTT min/mean/max/mdev and packet loss, iPerf3 throughput, and both model streaming measurements. `rtt_mdev_ms` is ICMP RTT variation, not packet-level jitter. For packet-level arrival timing, capture the relevant TCP flow on both gateway interfaces with `gateway/capture_chatbot_traffic.sh` and analyse the pcap with `analysis/pcap_interarrival.py`.
