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


| Split | n | MAE (MWh) | RMSE (MWh) | R² |
|---|---|---|---|---|
| Validation (2014) | 7158 | 1.364 | 1.740 | 0.9836 |
| Holdout (2015) | 7384 | 1.293 | 1.646 | 0.9896 |
| Naive: train mean (holdout) | 7384 | 12.957 | 16.185 | -0.0008 |
| Naive: previous observation (holdout) | 7383 | 4.125 | 8.467 | 0.7261 |

| Residual statistics (validation) | Value |
|---|---|
| residual_std_validation | 1.375 MWh |
| p01 / p05 / p50 / p95 / p99 | -2.24 / -0.93 / +1.02 / +3.70 / +4.58 MWh |
| trained_at_utc | 2026-11-04T18:28:34Z |

Note the validation residual median is +1.02 MWh: 2014 sits slightly above the 2011–2013 relation (year-to-year drift). The evidence engine therefore also compares the case window's residual against the residual of the 240 real reference rows preceding it (`values.z_vs_reference`), not only against the validation distribution.

### How to read these numbers

- The model learns the contemporaneous statistical relation between operating/ambient readings and output in one plant's data. It is **not** a thermodynamic model and cannot forecast.
- Residual = observed − expected TEY. A negative residual means output below what the learned relation implies for the measured conditions. Residuals are confounded by dispatch/load changes that the data set does not record as a separate signal.
- `residual_std_validation` and the validation quantiles are the only thresholds used by the evidence engine (`BaselineComparison.residual_z`). The holdout year plays no role in threshold selection.
- Beating the naive baselines shows that the features carry information about TEY; it does not show that the model detects faults, because no fault labels exist.

## Scenario behaviour (deterministic evidence engine)


| Scenario | Synthetic | Top deterministic hypothesis | Support score | Notable evidence IDs | Matches `expected_behavior`? |
|---|---|---|---|---|---|
| S01_NORMAL | no | unknown | 0.70 | — | yes (nothing notable; top = unknown) |
| S02_INTAKE_RESTRICTION | yes | intake_restriction | 1.00 | ev_afdp_01, ev_afdp_02, ev_tey_residual_02 | yes |
| S03_SENSOR_INCONSISTENCY | yes | sensor_issue | 0.85 | ev_tey_residual_01, ev_cdp_02 | yes |
| S04_AMBIENT_SHIFT | yes | operating_condition | 0.50 | ev_at_02 | yes (no fault claimed) |

Real-only control windows in 2015 (rows [500,620), [3000,3120), [6000,6120)) plus S01: **0 of 4** raised a notable residual flag. Produced by `python scripts/evaluate.py` → `docs/EVALUATION_RESULTS.json` (2026-11-04T18:28:45Z). Support scores are fixed-rule heuristics, not probabilities.

## Live Meta smoke test record

Produced by `make meta-smoke` (`scripts/meta_live_smoke.py`), which performs one real `chat/completions` call with function tools against `https://api.meta.ai/v1`. Record the output verbatim; the key is never printed.

Three real investigations were run through the full pipeline (`services.run_investigation_pipeline`, `use_meta=True`) on 2026-11-04 against `https://api.meta.ai/v1`. They are stored in `data/thermomind.db` and visible under `/investigations` in the UI. Token counts are from the API's `usage` field; latency is the sum of model-call round trips. The key is never printed.

| Scenario | Case id | Timestamp (UTC) | Model id returned | Model turns | Tool calls | Model latency (ms) | Tokens prompt / completion / reasoning | Validator | Rank-1 hypothesis | Report hash |
|---|---|---|---|---|---|---|---|---|---|---|
| S02_INTAKE_RESTRICTION | case_76d34565b3dc | 2026-11-04T18:32:03Z | muse-spark-1.3 | 4 | 10 (get_baseline_comparison, get_sensor_window, get_data_quality, list_evidence, evaluate_hypothesis, evaluate_hypothesis, evaluate_hypothesis, evaluate_hypothesis, get_sensor_window, lookup_reference) | 75040 | 42262 / 7234 / 4141 | accepted first pass | Intake restriction (possible) | `134a5460c43905de…` |
| S03_SENSOR_INCONSISTENCY | case_760658afb3d5 | 2026-11-04T18:33:19Z | muse-spark-1.3 | 3 | 9 (get_baseline_comparison, get_sensor_window, get_data_quality, evaluate_hypothesis, evaluate_hypothesis, list_evidence, get_sensor_window, evaluate_hypothesis, evaluate_hypothesis) | 43577 | 27663 / 4422 / 1733 | accepted first pass | Sensor issue / measurement inconsistency (CDP) (possible) | `f16579c471a71a9d…` |
| S01_NORMAL | case_b1d8db08ff82 | 2026-11-04T18:34:03Z | muse-spark-1.3 | 4 | 11 (get_baseline_comparison, get_data_quality, list_evidence, get_sensor_window, get_sensor_window, evaluate_hypothesis, evaluate_hypothesis, evaluate_hypothesis, evaluate_hypothesis, lookup_reference, lookup_reference) | 63817 | 36670 / 6816 / 3707 | accepted first pass | Unknown / no fault / normal variation (possible) | `92feaa1d7b532ff8…` |

The earlier standalone smoke (`scripts/meta_live_smoke.py`, 18:27:24 UTC, fake 3-evidence case) also completed: 5 model turns, 9 tool calls, 38,057 total tokens (5,843 reasoning), one rewrite because the validator flagged the word "command" in an engineer check; the rewrite was accepted.

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
