# Hackathon work statement

**Event:** Meta Global AI Developer Hackathon, Startup Track
(https://dev.meta.ai/events/global-hackathon, https://cerebralvalley.ai/e/meta-ai-developer-hackathon).
Event window 26 October – 4 November 2026. Submission deadline 4 November 2026, 9 PM ET.

## Statement

The repository's git history begins 2026-11-04 18:15 UTC; the project was restarted from an empty directory that day after earlier work became inaccessible. All code in this repository was written during the hackathon window. The only external inputs are the public UCI data set (CC BY 4.0), open-source dependencies listed in `apps/api/requirements.txt` and `apps/web/package.json`, and the Meta Model API.

The repository's first commit is `chore: initialize ThermoMind hackathon rebuild`.

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
| Tests | `apps/api/tests/` (8 test files incl. red-team and torch) | Pytest suite, fixture-only for the API tests |
| Web app | `apps/web/src/` (pages: Overview, Investigations, Investigation, DataSources, Evaluation, Replay; components, typed API client) | React + TypeScript + Vite + Tailwind + Recharts UI with provenance badges |
| Scripts | `scripts/` (`fetch_uci`, `train`, `train_torch`, `evaluate`, `seed_demo`, `meta_live_smoke`, `smoke_test.sh`, `e2e_browser.py`, `dev.sh`) | Data fetch, training, scenario evaluation, seeding, live Meta smoke, HTTP smoke, browser e2e |
| Build and CI | `Makefile`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Make targets, Docker image, CI |
| Plant-wide features | `apps/api/app/plant/`, `apps/api/app/features/{planner,instruments,emissions,thermal,grid,ops}/`, `apps/api/app/connectors/` | Inbox, what-if agents, planner, instruments, emissions, simulated thermal screening, synthetic grid drill, ops handover, simulated connectors (no control path) |
| Late features | `apps/api/app/features/{deliberation,watchdog,executive,collab,agents_tree}/`, `apps/web/src/features/`, 3D twin | Propose an action (deliberation, nothing executed), watchdog (simulated auxiliaries, policy), executive view, autonomy policy, onboarding brief, activity feed, domino map, 3D twin, agent tree, comparison, printable report, judge tour |
| Documentation | `README.md`, `AGENTS.md`, `docs/*.md`, `docs/EVALUATION_RESULTS.json`, `docs/screenshots/`, `submission/` | Architecture, provenance, safety, market, evaluation, demo, submission |

## Real numbers

- **Commits:** 62 commits in `git log --oneline` at the time of writing (history begins 2026-11-04 18:15 UTC).
- **Tests:** `cd apps/api && python -m pytest -q` -> `531 passed (backend), 52 passed (web) — 2026-11-05 00:35 UTC`.
- **Live Muse Spark investigations** (`muse-spark-1.3`, `https://api.meta.ai/v1`, recorded in `docs/EVALUATION.md`):
  - `case_76d34565b3dc` S02_INTAKE_RESTRICTION, 2026-11-04T18:32:03Z
  - `case_760658afb3d5` S03_SENSOR_INCONSISTENCY, 2026-11-04T18:33:19Z
  - `case_b1d8db08ff82` S01_NORMAL, 2026-11-04T18:34:03Z

## Process

The work was split among parallel agents, each owning one tree (`apps/api/app/data`, `apps/api/app/analytics`, `apps/api/app/agent`, `apps/api/app/api` + `db`, `apps/web`, `scripts`, docs/build), coordinated by a principal through `AGENTS.md` and the shared contract. Shared files (`schemas.py`, `config.py`, `contracts/`) were edited only by the principal.

## What is not claimed

No validation on a real plant, no pilot, no users, no revenue, no accuracy claim, no avoided-downtime claim. Metrics in `docs/EVALUATION.md` are filled only from runs of this code.

## How it was built: a tree of agents

ThermoMind was built the way it is organised (see `docs/AGENT_ORGANISATION.md`): a tree of agents with narrow ownership.

- **Principal agent (this session).** Wrote the contracts first (`contracts/api.md`, `schemas.py`, `config.py`, `AGENTS.md`), delegated work, merged results and made every commit. Specialist agents never ran `git commit`.
- **Specialist agents, one per module.** Data, ML, Meta agent, backend, frontend, docs, GPU, QA, performance, review and fix passes. Later feature agents: planner, instruments, emissions, ops, grid, thermal, connectors, compare, tour, 3D, twin, agent-tree and video.
- **Sub-agents.** Where a task split cleanly the specialist spawned its own, for example the frontend agent's animation probe, the plant-ops agent's UI sub-agent and the security review's web sub-agent.
- **Per-task model and effort.** Lighter model and lower effort for mechanical work (screenshots, doc fill-ins, lint, copying data); heavier model and higher effort for integration-critical or reasoning-heavy work (orchestration, debugging, cross-module changes). Sub-agents apply the same rule.
- **Rules every agent followed.** Explicit file ownership, a concrete deliverable, real command output in the report, shared files edited only by the principal (`AGENTS.md`, "Delegation policy").

This describes how the code was produced. It does not change what is claimed about the product: no validation on a real plant and no accuracy claim (see "What is not claimed").

## Not completed (honest record)

- The plant **physics simulator** (`/simulator`) was initially not built in the interrupted session; a reduced 0-D version was later added (`apps/api/app/simulator/`, see [SIMULATOR.md](SIMULATOR.md)). It is a lumped model calibrated to one plant's public data, not a digital twin of any facility, and its controls act on the model only. The page includes a generic animated schematic driven by the simulator.
- The 3D digital twin, deliberation ("Propose an action"), watchdog and executive view were built late on 4 November and verified by their own tests and typecheck; the final integrated build and e2e run happened in the last hour before the deadline.
