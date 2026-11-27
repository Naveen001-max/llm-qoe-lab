# Research Dataset — Data Dictionary

The canonical export is `/api/admin/export/study.json`; the chronological event ledger is `/api/admin/export/events.jsonl`; the request-level CSV is `/api/admin/export/requests.csv`.

| Group | Fields | Meaning / caution |
|---|---|---|
| Identity | participant_id | Pseudonymous participant code; no username in research exports |
| Study | experiment_id, protocol_version, ethics_approval_ref, seed | Experiment and approved protocol context |
| Trace | trace_id, assignment_id, task_code | Unique participant-task trace and assigned condition |
| Model | model_arm, repository, revision, engine_version, config_sha256, image digest | Frozen inference configuration |
| Network | latency_ms, jitter_ms, loss_pct, bandwidth_mbps | Configured impairment profile, not measured values |
| Server performance | ttft_ms, itl_mean_ms, tpot_ms, queue_time_ms, e2e_latency_ms | Server-observed. `queue_time_ms` is API semaphore admission wait, not vLLM scheduler queue. ITL is inter-SSE-output event gap unless token-per-event is confirmed. `tpot_ms` is an end-to-end post-first-output estimate; use vLLM's `request_time_per_output_token_seconds` histogram for engine TPOT. |
| Client performance | client_chat_ttft_ms, client_first_render_frame_ms, client_click_to_first_chunk_ms, client_chat_e2e_ms, client_click_to_completion_ms | Browser-observed using performance.now/requestAnimationFrame |
| Streaming | output_tokens, chunk_count, response_bytes, response_chars, finish_reason | output_tokens is provider usage; chunk count is application SSE delta events; bytes are UTF-8 response text bytes |
| Network measurements | ping RTT min/avg/max/mdev/loss, iPerf3 throughput, WAN egress and IFB ingress `tc -s qdisc` counters, tshark packet inter-arrival variation | qdisc snapshots are taken after profile application and before baseline reset. Request-window deltas preserve each qdisc separately; never sum parent and child qdiscs because hierarchical qdiscs can count the same packet at multiple levels. The window includes a small amount of gateway-control-plane traffic and is not a pure application-packet count. ICMP RTT, HTTPS RTT, TCP throughput, qdisc counters and packet inter-arrival variation are distinct measures. vLLM Prometheus histograms are aggregate engine metrics and are not individually joined to a participant trace. |
| User workload | NASA-TLX raw score and six subscales | Unweighted Raw TLX mean; not weighted NASA-TLX |
| QoE | six P.852-aligned local supplemental items and aggregate | Local items; not a certified/verbatim P.852 instrument |
| Task quality | blinded rubric criterion scores and total score | Independent scorer ratings; retain scorer pseudonyms for ICC |
| Lifecycle | event_type, occurred_at, payload | Event ledger with UTC timestamps |

Always retain the raw export, the analysis script version, the frozen model manifest and the calibration report. Do not overwrite raw data with cleaned/derived values. Document missingness, exclusions, participant withdrawals and any protocol deviations.
