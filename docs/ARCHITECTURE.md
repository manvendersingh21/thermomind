# Architecture

ThermoMind is a two-process development stack (FastAPI on 8000, Vite on 5173 proxying `/api`) that collapses into one Docker image for deployment (the Python stage serves `apps/web/dist` with SPA fallback). All shared types live in `apps/api/app/schemas.py` and mirror into `apps/web/src/api/types.ts`; `contracts/api.md` is the HTTP contract.

## Data flow

```
UCI zip ──fetch_uci.py──▶ data/raw/uci_551/gt_2011..2015.csv  (CC BY 4.0, never mutated)
                               │
                               ├─▶ app.data.uci_loader ─▶ DatasetBundle(frame: source_year,row_index,+11 measurements)
                               │        └─ DatasetRepository (SQLite registry, idempotent seed "ds_uci_551")
                               │
                               └─▶ scripts/train.py ─▶ app.analytics.train ─▶ data/models/baseline_v1.{joblib,json}
                                                                               (ModelEvaluation: chronological split,
                                                                                validation 2014, holdout 2015, naive baselines)

POST /api/investigations
   repo.get(dataset) ─▶ window [start,end) + reference (240 preceding real rows)
   ─▶ apply_scenario(copy)            synthetic overlay or none; Transformation list; synthetic flag
   ─▶ analyze_case(...)               Evidence[], DataQualityReport, BaselineComparison, HypothesisEvaluation{4}
   ─▶ run_investigation(...)          Muse Spark tool loop ─▶ validate_report ─▶ (one rewrite) ─▶ DiagnosticReport | needs_review
   ─▶ InvestigationStore.save         SQLite JSON blob: report, evidence, events, hashes
GET  /api/investigations/{id}        full Investigation (UI case page, /replay, export.json)
POST /api/investigations/{id}/review ReviewRecord (accepted | rejected | more_data_requested)
```

The model never sees the raw frame directly: it sees tool results, each of which carries evidence IDs. The validator only accepts IDs that the tool runner actually returned during that case.

## Components

| Component | Path | Responsibility | Key constraints |
|---|---|---|---|
| Data layer | `apps/api/app/data/` | Load UCI files or uploaded CSVs, validate columns, keep `source_year` + `row_index`, compute provenance (sha256, citation, notes), serve downsampled series (≤ 2000 points) | No timestamps fabricated; raw frames read-only; upload size/schema errors return 400/413/422 |
| Baseline model | `apps/api/app/analytics/train.py`, `baseline.py` | `HistGradientBoostingRegressor` predicting TEY (MWh) from AT, AP, AH, AFDP, GTEP, TIT, TAT, CDP; residuals; out-of-training-range counts | Chronological split train 2011–2013 / validation 2014 / holdout 2015; naive baselines `train_mean`, `previous_observation`; CO/NOX excluded (emission outputs) |
| Scenarios | `apps/api/app/analytics/scenarios.py` | Registry of S01–S04; seeded overlays applied to a copy; `Transformation` records | Original window never mutated; `expected_behavior` never sent to the model |
| Evidence engine | `apps/api/app/analytics/anomaly.py`, `evidence.py` | Window-vs-reference stats, z-scores, trend slopes, spikes, residual analysis, data-quality report, deterministic hypothesis support scores | Every `Evidence` carries `computation` with the actual numbers, `kind` (provenance), `is_synthetic`, flags |
| Meta client | `apps/api/app/agent/meta_client.py` | OpenAI-compatible `chat/completions` against `https://api.meta.ai/v1`, `muse-spark-1.3`, function tools; redaction; `ping()` | Key server-side only; reasoning tokens counted in `max_tokens`; stored messages reduced to role/content/tool_calls |
| Tools | `apps/api/app/agent/tools.py` | `get_sensor_window`, `get_baseline_comparison`, `evaluate_hypothesis`, `get_data_quality`, `list_evidence`, `lookup_reference` | Each call returns JSON + the evidence IDs it exposed; unknown tool/bad args raise `ToolError` |
| Orchestrator | `apps/api/app/agent/orchestrator.py` | Multi-turn tool loop (bounded by `META_MAX_TOOL_ROUNDS`), validation, one rewrite, fallback to `needs_review`; offline preview when no key | `meta_used=true` only after a real Meta call; `mode` is `meta_live` or `offline_preview` |
| Validator | `apps/api/app/agent/report_validator.py` | Parse → `DiagnosticReport`; reject unknown evidence IDs, case-ID mismatch, schema errors, fabricated dates, control instructions; `report_hash` | Report status is always `draft_requires_human_review` |
| API + storage | `apps/api/app/main.py`, `app/api/*`, `app/db/storage.py` | Routers per `contracts/api.md`; CORS allowlist; static `apps/web/dist`; SQLite `InvestigationStore` | Never 500 on user input; never leak the key |
| Web | `apps/web/` | React + TypeScript + Vite + Tailwind + Recharts; routes `/`, `/data`, `/investigations` (list), `/investigations/:id`, `/evaluation`, `/replay`; embeds the 'Combined Cycle Power Plant' interactive animation by educational-animation.org (MIT licence, https://www.educational-animation.org/en/combined-cycle-power-plant/). It is a generic educational plant, not the UCI facility. | Provenance badges: REAL PUBLIC DATA / MODEL-DERIVED / SYNTHETIC OVERLAY / HUMAN REVIEW REQUIRED |
| Scripts | `scripts/` | `fetch_uci.py`, `train.py`, `seed_demo.py`, `dev.sh`, `smoke_test.sh`, `meta_live_smoke.py` | Driven by the `Makefile` targets |
| Packaging | `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Two-stage image; `data/` volume; CI runs fixture-only pytest and the web typecheck/build | No secrets in image or CI |

## Sequence of one investigation

```
Engineer (UI /)                 API                          Analytics                     Muse Spark
   │ POST /api/investigations    │                              │                              │
   │ {dataset, S02, 2014,        │                              │                              │
   │  1200..1320, use_meta}      │                              │                              │
   │────────────────────────────▶│ window + reference frames    │                              │
   │                             │─────────────────────────────▶│ apply_scenario (copy, seed)  │
   │                             │                              │ analyze_case → evidence,     │
   │                             │                              │   data quality, baseline,    │
   │                             │                              │   hypothesis evals           │
   │                             │◀─────────────────────────────│                              │
   │                             │ event: case_opened                                          │
   │                             │ chat(messages, TOOL_SPECS) ─────────────────────────────────▶│
   │                             │ event: model_request                                        │
   │                             │◀──────────────────────────────── tool_calls[get_sensor_window, ...]
   │                             │ event: tool_call → ToolRunner.run → event: tool_result (evidence_ids)
   │                             │ ... repeat ≤ META_MAX_TOOL_ROUNDS ...                       │
   │                             │◀──────────────────────────────── final JSON report (response_format json_object)
   │                             │ validate_report(raw, case_id, known_evidence_ids, scenario_label)
   │                             │ event: validation (ok | errors)                             │
   │                             │ [if errors] event: rewrite_requested → one more chat ──────▶│
   │                             │ [ok] event: report_accepted, report_hash                    │
   │                             │ [still failing] status=needs_review + deterministic summary │
   │                             │ InvestigationStore.save                                     │
   │◀────────────────────────────│ {case_id, status}                                           │
   │ GET /api/investigations/id  │                                                             │
   │ render evidence, hypotheses, tool trace; engineer posts review decision                   │
```

Without `MODEL_API_KEY` the same path runs with `use_meta` effectively false: the orchestrator assembles an `offline_preview` from the deterministic tool outputs, `meta_used=false`, and the UI labels it "not a Meta inference".

## Why this shape

- **Evidence first, prose second.** The model's job is to select and explain, not to compute. Every number in a report can be traced to an `Evidence.computation` string.
- **Validation as a hard gate.** A hallucinated evidence ID cannot pass the gate, and control-language drafts are rejected by pattern matching.
- **Replayability.** The stored event trace lets anyone replay what the model requested and received, which is what an auditor or a sceptical reliability engineer will ask for first.
- **One image.** Plant IT teams prefer a single container with a mounted data directory over a multi-service deployment.

## Architecture: component map of the extension packages

Diagram: `docs/architecture.svg`. Feature-by-feature detail: `docs/FEATURES.md`.

| Package | Path | Role |
|---|---|---|
| Plant agents | `apps/api/app/plant/` | Personas, subsystem registry, work requests, notifications, precedent memory, sensitivity surrogate, what-if multi-agent (`whatif.py`), `recall_similar_cases` tool hook |
| Second opinion | `apps/api/app/analytics/second_opinion.py`, `torch_baseline.py`, `comparison.py` | GPU MLP challenger and HGBR comparison; `second_opinion_only`, never production |
| Planner | `apps/api/app/features/planner/` | Compressor wash and filter change-out what-ifs from editable assumptions |
| Instruments | `apps/api/app/features/instruments/` | Sensor health scorecard |
| Emissions | `apps/api/app/features/emissions/` | CO / NOx views |
| Thermal | `apps/api/app/features/thermal/` | Simulated thermal screening (`simulated_from_real_load`) |
| Grid | `apps/api/app/features/grid/` | Readiness, synthetic S05_GRID_EVENT drill with one Meta brief call, contingency options |
| Ops | `apps/api/app/features/ops/` | Handover note (Meta, no tools), CMMS export, pilot metrics |
| Connectors | `apps/api/app/connectors/` | Simulated historian, CMMS, notifier; `control_system.py` is a refusal stub |
| Web feature pages | `apps/web/src/{plant,features}/` | Inbox, Ask, Planner, Instruments, Emissions, Thermal, Grid, Connectors, Ops, tour |

All of these are read-only with respect to the plant: no package has a control write path.
