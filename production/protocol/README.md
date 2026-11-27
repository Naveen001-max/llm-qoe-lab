# WP4 — Experimental protocol package (draft for supervisor/ethics review)

## Study objective

Estimate how network-level conditions and inference model scale influence the technical performance and participant-perceived quality of streaming text-chatbot interactions.

## Design

- Within-participant repeated-measures design with 12 controlled tasks.
- Two inference arms: one LLM and one SLM, frozen to immutable model revisions.
- Four network profiles: baseline, moderate, high-delay and constrained.
- Each participant receives a seeded random task order and a shuffled sequence of model/network conditions. The 12 tasks sample the 2 × 4 condition matrix; four of the eight combinations repeat per participant. The exact allocation is stored per assignment.
- Record all randomisation seed, protocol version, model revision, inference settings, gateway profile acknowledgement and UTC timestamps.
- Do not run concurrent participants through a single shared tc/netem gateway unless the scheduler serializes the full request. The API currently serializes the full LLM request while one global gateway profile is active.

## Twelve task set

1. Factual explanation — networking concepts.
2. Structured summarisation — five-bullet summary.
3. Multi-step reasoning — data-rate calculation.
4. Instruction following — constrained comparison table.
5. Code comprehension — identify and fix an edge case.
6. Information extraction — schema-constrained JSON.
7. Planning — safe SQLite-to-PostgreSQL migration.
8. Translation — technical English-to-Hindi translation.
9. Classification — QoS, inference performance and QoE.
10. Numerical interpretation — mean, median and range.
11. Constraint consistency — workshop planning with multiple constraints.
12. Critical evaluation — QoS/QoE claim and testable hypothesis.

Task prompts and criterion-level rubrics are versioned in `app/protocol.py`. These are proposed task materials, not a validated psychometric test. Supervisor review and a pilot are required before use.

## Rubric scoring

- Score each criterion from 0 to 100.
- Criterion weights sum to 100 within each task.
- Weighted task score = sum(criterion score × criterion weight) / sum(weights).
- Use at least two independent scorers for a pre-specified subset or all responses.
- Blind scorers to participant identity, model arm and network profile. The scorer queue omits those fields; do not expose the admin dataset to scorers.
- Report inter-rater agreement and adjudicate disagreements using a documented procedure.

## Subjective measures

### NASA-TLX
The digital form implements the six NASA-TLX subscales: mental demand, physical demand, temporal demand, performance, effort and frustration. The current form records raw ratings (0–100, 5-point steps) and computes Raw TLX as their arithmetic mean. If the weighted NASA-TLX is required, implement the 15 pairwise factor comparisons and calculate each participant's dimension weights; do not infer weights from the raw ratings. Follow the [NASA TLX official page](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/) and [NASA paper-and-pencil package](https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20000021488.pdf) for anchors, instructions and scoring. NASA's official procedure uses six subscales and the weighted method uses pairwise importance comparisons; this application currently implements the unweighted Raw TLX mean, not the weighted comparison procedure.

### P.852-aligned QoE supplement
The application includes six local supplemental ratings for overall interaction quality, answer relevance, completeness, ease of interaction, response clarity and satisfaction. These are labelled as **P.852-aligned local items**, not a verbatim reproduction or certified implementation of ITU-T Recommendation P.852. The official [ITU-T P.852 recommendation page](https://www.itu.int/rec/T-REC-P.852/en) describes subjective laboratory evaluation of text-based chatbot interaction, including overall impression, information, communication, system behaviour, user impression and acceptability. Obtain and review the full Recommendation with the supervisor before finalising the instrument. Record questionnaire version and deviations.

## Participant instructions (draft)

1. You will complete 12 short tasks using a text chatbot.
2. Follow the task instruction and submit the requested prompt.
3. Do not enter your name, contact details, passwords or other sensitive personal information into the chatbot.
4. Wait until the response stream completes, then complete the QoE and workload questions.
5. You may pause or withdraw according to the approved consent procedure.
6. Do not refresh or close the browser during a task unless instructed; if interrupted, inform the study operator.
7. There are no trick questions. Your interaction and feedback are used for research after approval and de-identification.

## Consent and ethics checklist

This is a template only; it is not a substitute for the institution's approved consent form. The application enforces a formal ethics approval reference before randomisation and requires each participant to accept the current consent version before assignments can be created or executed. The admin approval flag is an auditable operator attestation; it does not itself constitute or verify institutional approval.

- Study purpose, procedures and expected duration.
- Voluntary participation and right to withdraw without penalty. The interface disables further access after withdrawal; any data deletion or retention must follow the approved consent and institutional policy.
- Potential risks/discomfort and expected benefits (if any).
- Data collected: prompt/response text, timing telemetry, task results, network measurements, questionnaire responses and pseudonymous participant ID.
- Data controller, storage location, access roles, retention period and deletion process.
- Whether data may be shared, published or reused; anonymisation/pseudonymisation limits.
- Contact details for investigator and institutional ethics committee.
- Consent checkbox and timestamp stored separately from study response data where required by the institution.
- No recruitment or main-study data collection before written ethics approval and site permission.

## WP5 calibration / pilot checklist

- Verify chrony source, offset, stratum and reach on gateway, emulator, API and inference hosts.
- Confirm client route to inference endpoint uses the gateway as next hop.
- Capture flow metadata simultaneously on LAN and WAN interfaces; verify matching flow crosses both.
- Verify no alternate Wi-Fi/VPN/IPv6/default route bypass exists on test hosts.
- Apply each profile and retain `tc -s qdisc`, nftables counters and iPerf3 JSON results.
- Run baseline and impaired inference tests for both model arms; repeat each profile at least 10 times during calibration (final repeat count should follow the study's power analysis).
- Verify server and browser timestamps, trace IDs, request IDs, SSE event order, JSONL and PostgreSQL records.
- Confirm model revision, tokenizer, chat template, inference image digest, GPU/driver and generation parameters are frozen.
- Run a small human pilot only after ethics approval; interview participants about task clarity and questionnaire burden.

## WP6 analysis plan (pre-registration recommended)

Primary outcomes:
- Client-observed TTFT and end-to-end response latency.
- Server-side vLLM TTFT, queue time, ITL and TPOT where exposed.
- P.852-aligned supplemental QoE score and task rubric score.
- NASA-TLX raw workload score.

Secondary outcomes:
- Network throughput, RTT, packet drops/retransmissions and packet inter-arrival variation.
- Completion rate, finish reason, output length and participant response latency.

Analysis:
- Descriptive summaries and distributions by model arm × network profile.
- Mixed-effects regression with participant random intercepts and fixed effects for model, latency, jitter, loss, bandwidth, task and order.
- Spearman/Pearson associations between technical metrics, workload, QoE and rubric scores, with assumptions checked.
- Compare models using participant-grouped cross-validation; no random row split that leaks repeated participant observations.
- Report confidence intervals, effect sizes, missingness, exclusions and sensitivity analyses.
- Validate predictive performance on held-out participants and report calibration as well as discrimination/error.
