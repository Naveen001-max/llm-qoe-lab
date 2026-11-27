# Production consolidation and NetEm qdisc telemetry

The legacy root dashboard, its static frontend, root-level backend/persistence/export modules, root Docker/Compose stack, and proxy-container NetEm implementation have been removed from this clean distribution. `production/` is the only application. The only network impairment controller is the authenticated external Ubuntu gateway agent.

The gateway agent parses `tc -s qdisc show` for WAN egress and IFB ingress and returns per-qdisc bytes, packets, drops, overlimits and requeues. The API stores the profile-applied start snapshot, reads the end snapshot before baseline reset, computes per-qdisc deltas, and records them as `network_qdisc_measurement` joined to the request ID. CSV, full JSON and Excel exports carry the deltas; the event ledger preserves full snapshots. The React admin Network Controls page shows current qdisc counters.

The moral-dilemma Alembic migration now checks whether its tables and indexes already exist. This addresses the reported duplicate `experiment_consents` table failure without deleting or recreating the PostgreSQL database.

Counters are interface-wide, not flow-attributed. Parent/child qdiscs are kept separate. The request window includes a small amount of gateway control traffic. qdisc counters are not jitter; packet inter-arrival analysis still requires packet capture.

Python compilation, shell syntax checks, qdisc parser/delta checks and TypeScript syntax transpilation were run in the packaging environment. Full Docker/database/provider/TLS/physical-gateway/React production-build checks require the deployment environment and were not run here.
