# LLM QoE Lab — Production Research Platform

This repository contains one authoritative application stack under [`production/`](production/).

- React + TypeScript frontend: `production/web/`
- FastAPI backend: `production/app/`
- PostgreSQL + Redis: `production/docker-compose.yml`
- Authenticated external Ubuntu Linux NetEm agent: `production/gateway/`
- NetEm qdisc packet/byte/drop counter telemetry and research exports: `production/app/`
- Prometheus + Grafana: `production/observability/`

The legacy dashboard, its backend, static frontend, proxy-container NetEm stack and root-level persistence/export modules have been removed. The external Linux gateway agent is the only network impairment controller.

Start with [`production/README.md`](production/README.md). Physical NetEm experiments require a dedicated Ubuntu gateway and a verified participant traffic path. WSL2 is for application development, not shaping the Windows physical NIC.
