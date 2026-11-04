# Evaluation

All numbers in this file must come from running the code in this repository. Placeholders are left empty on purpose; nothing is estimated.

## Baseline model

| Item | Value |
|---|---|
| Model | `sklearn.ensemble.HistGradientBoostingRegressor` |
| Model id / version | `baseline_tey_hgbr` / `baseline_v1` |
| Target | TEY (MWh, as published) |
| Features | AT, AP, AH, AFDP, GTEP, TIT, TAT, CDP (CO and NOX excluded: combustion outputs, would leak target-correlated information) |
| Split | chronological by `source_year`: train 2011–2013, validation 2014, holdout 2015 (holdout never used for fitting or threshold selection) |
| Seed | 42 |
| Produced by | `make train` → `scripts/train.py` → `data/models/baseline_v1.json` (`ModelEvaluation`); served by `GET /api/models/evaluation`; shown on `/evaluation` |

### Metrics

<!-- FILLED BY PRINCIPAL AFTER RUN: copy values verbatim from data/models/baseline_v1.json produced by `make train` (the ML agent also wrote docs/EVALUATION_RESULTS.json with model metrics and per-scenario case results). Do not round beyond 3 decimals; do not type numbers from memory. -->

| Split | n | MAE (MWh) | RMSE (MWh) | R² |
|---|---|---|---|---|
| Validation (2014) | | | | |
| Holdout (2015) | | | | |
| Naive: train mean (holdout) | | | | |
| Naive: previous observation (holdout) | | | | |

| Residual statistics (validation) | Value |
|---|---|
| residual_std_validation | |
| p01 / p05 / p50 / p95 / p99 | |
| trained_at_utc | |

### How to read these numbers

- The model learns the contemporaneous statistical relation between operating/ambient readings and output in one plant's data. It is **not** a thermodynamic model and cannot forecast.
- Residual = observed − expected TEY. A negative residual means output below what the learned relation implies for the measured conditions. Residuals are confounded by dispatch/load changes that the data set does not record as a separate signal.
- `residual_std_validation` and the validation quantiles are the only thresholds used by the evidence engine (`BaselineComparison.residual_z`). The holdout year plays no role in threshold selection.
- Beating the naive baselines shows that the features carry information about TEY; it does not show that the model detects faults, because no fault labels exist.

## Scenario behaviour (deterministic evidence engine)

<!-- FILLED BY PRINCIPAL AFTER RUN: for each scenario, run `make seed` (or POST /api/investigations with use_meta=false) at the default window (2014, [1200,1320), seed 42) and record which evidence items are flagged and the deterministic_support_score per hypothesis from the stored Investigation. -->

| Scenario | Synthetic | Top deterministic hypothesis | Support score | Notable evidence IDs | Matches `expected_behavior`? |
|---|---|---|---|---|---|
| S01_NORMAL | no | | | | |
| S02_INTAKE_RESTRICTION | yes | | | | |
| S03_SENSOR_INCONSISTENCY | yes | | | | |
| S04_AMBIENT_SHIFT | yes | | | | |

## Live Meta smoke test record

Produced by `make meta-smoke` (`scripts/meta_live_smoke.py`), which performs one real `chat/completions` call with function tools against `https://api.meta.ai/v1`. Record the output verbatim; the key is never printed.

<!-- FILLED BY PRINCIPAL AFTER RUN -->

| Field | Value |
|---|---|
| Timestamp (UTC) | |
| Base URL | |
| Model id returned by the API | |
| Latency (ms) | |
| Tool calls made (names, in order) | |
| Tool rounds | |
| Tokens (prompt / completion / reasoning) | |
| Validator result (accepted / rewrite_requested / needs_review) | |
| Case id of the stored live investigation | |
| Report hash | |

## Test suite

<!-- FILLED BY PRINCIPAL AFTER RUN: paste the last lines of `cd apps/api && python -m pytest -q` and `cd apps/web && npm run typecheck`. -->

```
(pytest output)
```

```
(typecheck output)
```

## What is not evaluated

- Diagnostic accuracy of Muse Spark reports: there is no ground truth. The validator checks provenance and form, not correctness.
- Generalisation to other turbines, plants or years.
- False-alarm rate on real operations: S01 is a single control window, not a false-alarm study.
- Engineer time saved, acceptance rate, deployment time: these are the metrics a pilot would need to measure (see `docs/MARKET.md`).
