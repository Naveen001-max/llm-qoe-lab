# LLM QoE Lab — Production Full-Stack Platform

This repository contains one authoritative application stack. The legacy root dashboard, its separate backend, the proxy-container NetEm implementation and the duplicate static frontend have been removed.

## Architecture

- `app/` — FastAPI backend, PostgreSQL/SQLAlchemy, Redis coordination, authentication, experiment protocol, streaming, telemetry and exports.
- `web/` — React + TypeScript administrator, participant and scorer interfaces.
- `gateway/` — authenticated external Ubuntu Linux gateway agent and `tc/netem` + IFB setup.
- `migrations/` — Alembic schema history.
- `inference/` — optional separate LLM/SLM inference services and model manifests.
- `observability/` — Prometheus and Grafana configuration.
- `protocol/` — controlled tasks, rubrics, questionnaires and dataset dictionary.

## Selected network-emulation architecture

The production platform uses the **external Linux gateway agent**. It does not use an LLM HTTP proxy container. A dedicated Ubuntu gateway routes participant traffic to the application and applies Linux `tc/netem` on its WAN interface; ingress is redirected to `ifb0` for the reverse direction. The FastAPI service controls the agent over authenticated HTTPS.

The agent returns raw `tc -s qdisc show` output and structured per-qdisc counters. The API stores a qdisc snapshot after profile application, reads another snapshot before resetting the profile, calculates per-qdisc deltas for bytes, packets, drops, overlimits and requeues, and records a `network_qdisc_measurement` event joined to the request ID. WAN egress and IFB ingress remain separate. Parent and child qdiscs must not be summed because hierarchical qdiscs can count the same packet at multiple levels.

The React admin Network Controls page displays live qdisc counters when the gateway is reachable. Request CSV, full study JSON, Excel Requests sheet and Event Ledger include request-window qdisc measurements and their snapshots.

**Measurement boundary:** counters are interface/qdisc-wide, not per-flow. The measurement window starts after profile application and ends before baseline reset; it includes a small amount of gateway-control-plane traffic and may include other traffic on the dedicated interface. Do not label qdisc counters as jitter. Use packet capture/inter-arrival analysis for packet-level jitter. HTTPS RTT, ICMP RTT, qdisc counters and throughput are separate measurements.

## Physical topology and deployment

Use the dedicated two-NIC Ubuntu gateway described in [`gateway/README.md`](gateway/README.md). Do not install the privileged gateway on a shared campus or production network without explicit network-owner approval. WSL2 can run the application stack for development, but it is not a dependable physical Linux gateway for shaping the Windows Ethernet adapter. Real physical-path measurements require the external Ubuntu gateway and a separate participant computer whose traffic is verified to traverse it.

## Configure the production application

```bash
cp .env.production.example .env.production
# Edit .env.production locally; do not share it or commit it.
docker compose --env-file .env.production -f docker-compose.yml config --quiet
docker compose --env-file .env.production -f docker-compose.yml up -d --build
docker compose --env-file .env.production -f docker-compose.yml ps
```

The API container runs Alembic migrations before starting. If startup reports a migration conflict, inspect the Alembic revision and PostgreSQL schema; do not delete the PostgreSQL volume. The moral-dilemma migration checks for existing tables and indexes before creating them.

Create the first administrator interactively:

```bash
docker compose --env-file .env.production -f docker-compose.yml exec -it api python -m app.cli create-admin --username admin
```

Open `https://<PUBLIC_DOMAIN>`. Configure model provenance and complete deployment checks before creating an experiment. Formal human-subject randomisation requires genuine institutional ethics approval and participant consent. Synthetic technical checks must not be represented as an approved human study.

## Gateway configuration

- API: `GATEWAY_CONTROL_URL=https://qoe-gateway.lab:8090`
- Agent token: identical high-entropy `GATEWAY_TOKEN` and `QOE_GATEWAY_TOKEN` values
- CA: install the issuing CA certificate at `GATEWAY_CA_BUNDLE` inside the API container
- Gateway: bind the agent to the dedicated gateway host and restrict TCP/8090 to the API host only
- Enforcement: keep `REQUIRE_GATEWAY=true` for real network-condition experiments

The gateway agent is installed as a host systemd service, not as a Docker service. The compose stack contains only the application, database/cache, web ingress and observability components.

## Validation

Run `bash production/run_full_validation.sh` from the repository root. It validates the React build, Compose configuration, database/cache/API readiness, configured provider endpoints and an isolated Linux NetEm namespace. Physical gateway routing and qdisc behavior still require a live external gateway and participant traffic-path verification.

## Security and research integrity

- Keep `.env.production`, inference environment files, TLS private keys and provider tokens outside version control and distributable archives.
- The gateway agent is privileged because it changes host qdiscs. Restrict management access to the API host.
- Keep PostgreSQL, Redis, Prometheus and Grafana private.
- Use encrypted backups and define data-retention/deletion rules.
- The software package is not proof of a physically installed gateway, verified traffic path, ethics approval or validated human-subject study.
