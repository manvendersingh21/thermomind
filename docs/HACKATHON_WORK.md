# Hackathon work statement

**Event:** Meta Global AI Developer Hackathon, Startup Track
(https://dev.meta.ai/events/global-hackathon, https://cerebralvalley.ai/e/meta-ai-developer-hackathon).
Event window 26 October – 4 November 2026. Submission deadline 4 November 2026, 9 PM ET.

## Statement

**Everything in this repository was written on 4 November 2026, during the event.** It is a from-scratch rebuild: the machine that held earlier work became inaccessible, so the project was restarted from an empty directory on 4 November 2026. **No prior code was reused.** The only external inputs are the public UCI data set (CC BY 4.0), open-source dependencies listed in `apps/api/requirements.txt` and `apps/web/package.json`, and the Meta Model API.

The repository's first commit (`chore: initialize ThermoMind hackathon rebuild`) and every file timestamp reflect that date.

## Components built today (4 November 2026)

| Component | Path | What was built |
|---|---|---|
| Contracts and shared schemas | `contracts/api.md`, `apps/api/app/schemas.py`, `apps/api/app/config.py` | HTTP contract, Pydantic types for datasets, series, model evaluation, scenarios, evidence, investigations, agent events, reviews, health; central configuration |
| Data layer | `apps/api/app/data/` | UCI loader (five yearly CSVs → one frame with `source_year`, `row_index`), CSV validator for uploads, dataset repository with SQLite registry and series downsampling, provenance notes and sha256 |
| Data fetch script | `scripts/fetch_uci.py` | Standard-library downloader with header and row-count verification |
| Baseline model | `apps/api/app/analytics/train.py`, `baseline.py`, `scripts/train.py` | HistGradientBoostingRegressor for TEY, chronological split, naive baselines, residual quantiles, feature ranges, `ModelEvaluation` JSON |
| Scenarios | `apps/api/app/analytics/scenarios.py` | S01–S04 registry; seeded copy-on-write overlays with `Transformation` records |
| Evidence engine | `apps/api/app/analytics/anomaly.py`, `evidence.py` | Window-vs-reference statistics, trend/spike detection, baseline comparison, data-quality report, deterministic hypothesis support |
| Meta client | `apps/api/app/agent/meta_client.py` | OpenAI-compatible client for `muse-spark-1.3` at `https://api.meta.ai/v1` with function tools, redaction, usage capture, ping |
| Agent tools, orchestrator, validator | `apps/api/app/agent/tools.py`, `orchestrator.py`, `report_validator.py` | Six tools, bounded tool loop, report validation (evidence-ID whitelist, case id, schema, dates, control language), one rewrite, offline preview |
| API and storage | `apps/api/app/main.py`, `apps/api/app/api/`, `apps/api/app/db/` | FastAPI routers per contract, SQLite investigation store, static serving of the web build, health and demo status |
| Tests | `apps/api/tests/` | Fixture-only pytest suite |
| Web app | `apps/web/` | React + TypeScript + Vite + Tailwind + Recharts: `/`, `/data`, `/investigations/:id`, `/evaluation`, `/replay`; provenance badges; typed API client |
| Operational scripts | `scripts/seed_demo.py`, `dev.sh`, `smoke_test.sh`, `meta_live_smoke.py` | Demo seeding, dev launcher, HTTP smoke test, live Meta smoke test |
| Build and CI | `Makefile`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Make targets, two-stage Docker image, compose with `data/` volume, CI for pytest and web typecheck/build |
| Documentation and submission | `README.md`, `docs/*.md`, `submission/*.md`, `contracts/examples/investigation.json`, `LICENSE` | This document set, pitch, demo script, checklists, MIT licence |

## Process

The work was split among parallel agents, each owning one tree (`apps/api/app/data`, `apps/api/app/analytics`, `apps/api/app/agent`, `apps/api/app/api` + `db`, `apps/web`, `scripts`, docs/build), coordinated by a principal through `AGENTS.md` and the shared contract. Shared files (`schemas.py`, `config.py`, `contracts/`) were edited only by the principal.

## What is not claimed

No validation on a real plant, no pilot, no users, no revenue, no accuracy claim, no avoided-downtime claim. Metrics in `docs/EVALUATION.md` are filled only from runs of this code.
