# Hackathon work statement

**Event:** Meta Global AI Developer Hackathon, Startup Track
(https://dev.meta.ai/events/global-hackathon, https://cerebralvalley.ai/e/meta-ai-developer-hackathon).
Event window 26 October – 4 November 2026. Submission deadline 4 November 2026, 9 PM ET.

## Statement

**Everything in this repository was written on 4 November 2026, during the event.** It is a from-scratch rebuild: the machine that held earlier work became inaccessible, so the project was restarted from an empty directory on 4 November 2026. **No prior code was reused.** The only external inputs are the public UCI data set (CC BY 4.0), open-source dependencies listed in `apps/api/requirements.txt` and `apps/web/package.json`, and the Meta Model API.

The repository's first commit (`chore: initialize ThermoMind hackathon rebuild`) and every file timestamp reflect that date.

## Components built today (4 November 2026)

Inventory as of the last commit in this section, from `find apps scripts docs -type f` and `git log`.

| Module / file group | Path | One line |
|---|---|---|
| Contracts and schemas | `contracts/api.md`, `apps/api/app/schemas.py`, `apps/api/app/config.py` | HTTP contract, Pydantic types, central configuration |
| Data layer | `apps/api/app/data/` (`uci_loader`, `validator`, `repository`, `provenance`) | UCI loader (`source_year`, `row_index`), upload validator, SQLite-registered dataset repository, provenance and sha256 |
| Baseline model | `apps/api/app/analytics/train.py`, `baseline.py`, `scripts/train.py` | HistGradientBoostingRegressor for TEY, chronological split, naive baselines, `ModelEvaluation` JSON |
| GPU challenger | `apps/api/app/analytics/torch_baseline.py`, `comparison.py`, `scripts/train_torch.py`, `requirements-gpu.txt` | Optional PyTorch MLP benchmarked on the same split; role `challenger`, not production |
| Scenarios | `apps/api/app/analytics/scenarios.py` | S01-S04, seeded copy-on-write synthetic overlays with transformation records |
| Evidence engine | `apps/api/app/analytics/anomaly.py`, `evidence.py`, `_io.py` | Window-vs-reference statistics, baseline comparison, data-quality report, deterministic hypothesis support |
| Meta agent | `apps/api/app/agent/` (`meta_client`, `tools`, `orchestrator`, `prompts`, `report_validator`, `_fake_case`) | `muse-spark-1.3` tool loop with six tools, report validator, one rewrite, offline preview |
| API and storage | `apps/api/app/main.py`, `services.py`, `api/` (datasets, scenarios, investigations, models, demo, health), `db/storage.py` | FastAPI routers, SQLite case store, pipeline service, static web serving |
| Tests | `apps/api/tests/` (9 test files incl. red-team and torch) | Pytest suite, fixture-only for the API tests |
| Web app | `apps/web/src/` (pages: Overview, Investigations, Investigation, DataSources, Evaluation, Replay; components, typed API client) | React + TypeScript + Vite + Tailwind + Recharts UI with provenance badges |
| Scripts | `scripts/` (`fetch_uci`, `train`, `train_torch`, `evaluate`, `seed_demo`, `meta_live_smoke`, `smoke_test.sh`, `e2e_browser.py`, `dev.sh`) | Data fetch, training, scenario evaluation, seeding, live Meta smoke, HTTP smoke, browser e2e |
| Build and CI | `Makefile`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Make targets, Docker image, CI |
| Documentation | `README.md`, `AGENTS.md`, `docs/*.md`, `docs/EVALUATION_RESULTS.json`, `docs/screenshots/`, `submission/` | Architecture, provenance, safety, market, evaluation, demo, submission |

## Real numbers

- **Commits (all 2026-11-04 UTC):** 10 commits from `e6364fd` at 18:15:57 (initial contracts, schemas, config, fixtures) to `6456503` at 18:39:34. Others: data layer 18:22:29; docs/CI/Docker 18:28:57; contract update 18:29:18; analytics 18:30:00; agent 18:30:13; API 18:30:13; fix 18:31:48; evaluation 18:36:29. (Later work in the tree is uncommitted at the time of writing.)
- **Tests:** `cd apps/api && python -m pytest -q` -> `140 passed, 1 warning in 72.79s`.
- **Live Muse Spark investigations** (`muse-spark-1.3`, `https://api.meta.ai/v1`, recorded in `docs/EVALUATION.md`):
  - `case_76d34565b3dc` S02_INTAKE_RESTRICTION, 2026-11-04T18:32:03Z
  - `case_760658afb3d5` S03_SENSOR_INCONSISTENCY, 2026-11-04T18:33:19Z
  - `case_b1d8db08ff82` S01_NORMAL, 2026-11-04T18:34:03Z

## Process

The work was split among parallel agents, each owning one tree (`apps/api/app/data`, `apps/api/app/analytics`, `apps/api/app/agent`, `apps/api/app/api` + `db`, `apps/web`, `scripts`, docs/build), coordinated by a principal through `AGENTS.md` and the shared contract. Shared files (`schemas.py`, `config.py`, `contracts/`) were edited only by the principal.

## What is not claimed

No validation on a real plant, no pilot, no users, no revenue, no accuracy claim, no avoided-downtime claim. Metrics in `docs/EVALUATION.md` are filled only from runs of this code.
