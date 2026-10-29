# LLM Network & QoE Monitoring Lab — Real Network Emulation

This version routes LLM HTTPS requests and HTTPS probes through a dedicated Linux TCP CONNECT proxy. Linux `tc/netem` applies real packet delay, jitter, and loss to the proxy's **inbound and outbound** interface traffic. The browser-to-dashboard connection is not routed through the emulator.

The UI reports a setting as applied only when the control service confirms the kernel commands succeeded. If IFB, `tc`, or `NET_ADMIN` is unavailable, the UI reports an error instead of silently falling back to a visual simulation. The current compose layout separates the shaped data plane from the unshaped control plane: Gemini proxy traffic and probes use the `data` network, while status polling and slider-control calls use the `control` network. This prevents the dashboard's own two-second polling requests from being counted as shaped data-plane packets.

## Requirements

- Windows 10/11 with current Docker Desktop using Linux containers, or a Linux host with Docker Engine
- Docker Compose v2
- A Google Gemini API key (Google AI Studio)
- Internet access

> Important: this is real traffic shaping on the dedicated proxy path, not a physical change to your Wi-Fi/mobile network. It affects traffic routed through the emulator, including LLM HTTPS streams and HTTPS probes. TCP retransmission can hide packet loss from the application while still increasing latency. Configured loss is not the same as a measured end-to-end packet-loss percentage.

## Run on Windows (recommended real-emulation mode)

1. Extract this folder and open PowerShell inside `llm_qoe_lab`.
2. Start Docker Desktop and make sure it is using Linux containers.
3. Set the API key in the current PowerShell session and start the containers:

   ```powershell
   $env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"
   $env:GEMINI_MODEL = "gemini-3.8-flash"
   docker compose up --build
   ```

   The app uses the native Gemini `streamGenerateContent` endpoint. You can choose any Gemini model available to your API key in the Model field.

4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).
5. Wait for **NETEM READY · BASELINE** (zero added impairment) or **IMPAIRMENT ACTIVE** (non-zero shaping) status. If the status says **UNAVAILABLE** or **APPLY FAILED**, read the displayed error and the `netem` container logs. Do not treat the experiment as shaped until the UI confirms success.
6. Move a slider and release it, or choose a profile. The change is applied immediately on release. The event log records the requested settings, confirmation or failure, applied values, timestamp, interface, and directions.
7. To stop the containers, run `docker compose down` in the project folder.

Useful diagnostics:

```powershell
docker compose ps
docker compose logs netem
docker compose logs app
```

## Native Python mode

The old native Windows command (`python -m uvicorn app:app ...`) can still serve the UI and chatbot, but it **cannot apply real Linux `tc/netem` shaping**. The network-emulation controls will report that real emulation is unavailable. Use Docker Compose for actual packet shaping; do not describe native-mode slider values as real network impairments.

## What the controls mean

- **One-way delay**: the configured base delay is applied once in each direction. Approximate added RTT is about twice the configured value, plus jitter and other network/provider delays. The supported slider range is 0–250 ms per direction.
- **Jitter**: the value is the standard deviation for a normal-distribution delay variation, not a hard `±` bound. It is applied in both directions. The supported range is 0–40 ms; use a non-zero base delay to make the variation interpretable.
- **Packet loss**: `tc netem` uses an explicit independent random packet-drop probability in both directions. The supported range is 0–3%. Observed drops are stochastic, so repeated trials will not necessarily drop the same number of packets. TCP retransmits many losses, so an LLM response may slow down or fail rather than simply lose visible text.
- **Traffic isolation**: `netem` is attached to two Docker networks. `eth0` is the first-attached data network and is shaped; the control network is separate and unshaped. Check `docker compose logs netem` and `tc -s qdisc show dev eth0 root` inside the netem container if packet counters do not behave as expected.
- **Profiles**: approximate impairment overlays (baseline, good Wi-Fi, typical mobile, weak mobile, congested link, poor radio link). These are reproducible test presets, not a claim that every real Wi-Fi/4G/5G connection has these exact values. A preset is active only after the kernel confirms application.
- **LLM stream**: HTTPS CONNECT is tunneled end-to-end through the proxy; TLS is not decrypted. The proxy shapes TCP packets and does not edit model text.

The `tc/netem` configuration uses a Linux IFB device to redirect ingress traffic for shaping. The container needs `NET_ADMIN` and kernel IFB support. If either is unavailable in a particular Docker Desktop/Linux environment, bidirectional setup fails and the UI will not report success.

## Measurements and reporting

- **TTFT**: browser-observed time from send action to first visible model text. Includes model/provider and shaped network effects.
- **Total response time**: browser-observed time to stream completion.
- **HTTPS probes**: real requests routed through the same emulation proxy, so their timings are affected by the active profile.
- **Timestamped event log**: records slider/profile changes, apply requests, success/failure, request start, first token, received chunks, completion, probe results, and export events.
- **JSON / CSV export**: preserves session events and the emulator state reported by the backend.

For defensible experiments, run repeated trials at each profile, record the model/provider and prompt, use a stable target, and compare baseline (0/0/0) against shaped conditions. Do not use configured packet-loss percentage as if it were a direct measurement of loss observed by the application.

## Security

- Keep `GEMINI_API_KEY` in the shell environment; do not place it in frontend JavaScript or commit it.
- The dashboard binds to `127.0.0.1` only by default.
- Use only on systems and traffic paths you own or are authorized to test.


### Gemini availability handling

The chat endpoint retries transient 5xx/503 provider overloads up to three attempts per model using exponential backoff, then tries the configured `GEMINI_FALLBACK_MODELS` in order. The UI records retry/fallback events with timestamps. A 429 rate/quota error and 401/403 authentication errors are reported distinctly; retries cannot fix exhausted project quota or invalid credentials. Model availability depends on the models exposed to your Google AI Studio API key.


## Spatial UI + chunk/packet telemetry update

- The dashboard uses a pale spatial/brutalist visual system with high-contrast borders and layered cards.
- Live LLM chunk counters are separate from Linux `tc/netem` packet counters. Packet counters are collected from the outbound root qdisc and inbound IFB qdisc; they are unavailable when NetEm is not ready.
- The CSV export is a normalized ledger with metadata, summary metrics, request summaries, packet-counter samples and event rows. Request summaries include start/end qdisc snapshots and a request-window counter delta when both snapshots are available. The JSON export is organized into metadata, experiment configuration, summary, LLM stream metrics, network packet metrics, probes, event ledger and metric definitions.
- `LLM output rate cap` paces application delivery of streamed text using an approximate token estimate. It does not change Gemini's internal model inference speed and must be described as an application-level delivery-rate experiment.
- `Total transmission time` is browser-observed time from prompt submission until stream completion/failure.
- Actual packet counters are Linux qdisc counters, not a derived estimate from the configured packet-loss percentage. Zero-impairment netem qdiscs remain installed so baseline traffic is counted too. The dashboard distinguishes cumulative counters from request-window deltas (end minus start); deltas can still include any concurrent traffic through the same proxy, so HTTPS probes are disabled during an active chat request. The ingress IFB counter means packets entering the proxy container, not exclusively packets from Gemini; egress likewise means packets leaving the proxy container, not exclusively packets to Gemini. Validate with `tc -s qdisc show dev eth0 root` and `tc -s qdisc show dev ifb0 root` before formal experiments.


## Realism, counters, and interface design (v3.2)

- The control service now keeps zero-impairment `netem` qdiscs installed, so baseline packet counts remain visible instead of disappearing when sliders are zero.
- The status badge distinguishes **NETEM READY · BASELINE** from **IMPAIRMENT ACTIVE**. Readiness means the shaping path is installed; impairment active means at least one non-zero slider is applied.
- The UI uses an animated spatial network-path illustration, layered cards, a pale Haikei-inspired terrain pattern, and restrained motion primitives. Motion respects `prefers-reduced-motion`.
- Cumulative counters keep moving while the proxy sees packets; a failed chat request does not reset them. Per-request counters are computed from start/end snapshots and are displayed separately. They are not guaranteed to contain only one request if other traffic shares the proxy.
- Packet counters are direction-of-interface counters. IFB ingress includes packets arriving at the proxy container from either the app or upstream network; it must not be interpreted as “Gemini inbound only.”
- The supported experimental slider ranges are 0–250 ms added one-way delay, 0–40 ms jitter standard deviation, and 0–3% independent random packet loss. These ranges are intended to reduce accidental extreme settings, but the actual impact still depends on TCP behavior, model response size, the underlying route, and provider conditions.
- “LLM output speed” is an application-level delivery cap based on approximate token counts. It does not set Gemini's internal token-generation speed.

### Detailed stream timing and subjective QoE update (v3.3)

The dashboard now records:

- Browser-observed TTFT and total response duration.
- `server_done_timestamp` when the backend emits Gemini stream completion, and `eof_timestamp` when the browser observes the HTTP response body close.
- Each received response text delta: chunk number, UTF-8 text byte size, character count, estimated token count, and receive timestamp.
- Raw stream response bytes (includes server-sent-event framing and metadata) separately from UTF-8 response-text bytes.
- Browser-to-backend JSON request size separately from the backend's serialized Gemini request payload size and number of conversation content parts.
- Word-arrival samples and observed gaps between whitespace-separated words.
- A 1–5 subjective user experience rating and optional comment saved against the most recent request. The request record includes the configuration in force when the prompt was sent, timing, stream/chunk measurements, and packet-counter window.
- Human-readable event labels alongside machine-readable event types and structured details.

**Measurement limitation:** Gemini sends text deltas/chunks, not a timestamp for every generated word or model token. Words within the same received chunk share the same browser-observed arrival time and therefore have a measured gap of 0 ms. Inter-word gaps across chunks are only an observed chunk-boundary approximation, not the model's internal token-generation latency. Similarly, the frontend's request byte count measures the browser-to-backend body; the backend's upstream payload byte count measures the serialized request it constructs for Gemini. Neither byte count alone proves that the provider accepted or processed the payload. The browser records stream EOF separately from the backend's `done` event.

The JSON report includes per-request `chunk_samples`, `word_arrival_samples`, `subjective_qoe`, timestamps, payload/stream byte counts, and packet deltas. CSV export includes request summary rows, word timing rows, QoE rating rows, network samples, and the detailed event ledger. Keep the same prompt/model/configuration across trials when comparing subjective ratings.
