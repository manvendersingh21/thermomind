# ThermoMind load test

Harness: `scripts/load_test.py` (httpx + threads). Server: own uvicorn on port 8040, scratch SQLite DB, real UCI data, real model dir, live Meta key (muse-spark-1.3). Host has 96 cores. Run on 2026-11-04. App code was not modified. Single uvicorn worker.

Run: `python scripts/load_test.py --base http://127.0.0.1:8040 --pid <server pid> [--skip-live] [--out r.json]`

## Results (run 2, warm server, default thread settings)

| Phase | Result |
|---|---|
| 1. 50 concurrent mixed requests (health, series x2 variants, preview POST, models/evaluation) | 50/50 2xx, 0 non-2xx. Overall p50 14.7 s, p95 38.7 s, max 39.8 s, wall 40.6 s |
| 2. 8 concurrent offline investigations (use_meta=false, 4 scenarios, years 2011-2015, different windows/seeds) | 8/8 HTTP 200, all `completed`, wall 15.1 s (10-15 s each). All case ids in `GET /api/investigations`, all GET-able, evidence lists non-empty, first 5 evidence ids per case resolve, no report cites an unknown evidence id |
| 3. 20 concurrent reviews on one case | 20/20 HTTP 200, 0 x 500, p95 2.2 s. Final review record (`rejected` / rev16 / c16) is one coherent, whole record from a successful request |
| 4. 2 concurrent LIVE Meta investigations (S02, S03) | Both HTTP 200 `completed`, `meta_used=true`, mode `meta_live`: S02 97.1 s, S03 78.7 s, wall 97.1 s. Evidence verification: no problems. Parallel `/api/health` polling every 2 s during the run (46 polls): all 200, p95 298 ms, max 1.3 s, so the event loop stays responsive |
| 5. Memory (RSS of server pid) | start 204-860 MB (see below) -> after phase 1 +21 MB -> after phase 2 +6 MB -> end 889 MB. Run 1 (cold): 203.6 MB start, 290 MB after phase 1, 861 MB after 8 offline investigations (+570 MB), 862 MB end |

Serial baselines (curl, idle server): health 4 ms, series 190 ms, models/evaluation 89 ms, preview 0.49 s, offline investigation 1.2 s.

Cold run (run 1, fresh server): phase 1 p50 9.9 s / p95 36.1 s, all 2xx; phase 2 wall 53.8 s (8/8 completed); phase 3 clean. Run 3 (fresh server, `OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4`, offline phases only): phase 1 p50 5.1 s / p95 20.8 s (about 2x better), phase 2 wall 29.7 s (8/8 completed), phase 3 clean. Variance between runs is large (phase 2 wall 15-54 s), so treat latency numbers as indicative.

## Server log
No `database is locked`, traceback, error, exception or HTTP 500 in either server log (`grep -ciE "locked|traceback|error|exception| 500 "` = 0 for runs 1, 2 and 3). Log tail (run 2, non-access lines):

```
httpx: HTTP Request: POST https://api.meta.ai/v1/chat/completions "HTTP/1.1 200 OK"
thermomind.plant.work_requests: work request wr_e42a1c5985 -> mechanical_maintenance_engineer (rule:intake_restriction) for case_dd7ab442248d
thermomind.services: investigation case_dd7ab442248d completed (scenario=S02_INTAKE_RESTRICTION mode=meta_live meta_used=True evidence=18)
INFO: Shutting down / Application shutdown complete.
```

## Verdict
Correctness under concurrency: PASS. No 5xx, no SQLite lock errors (WAL + per-call connections + 10 s timeout work), no lost cases, evidence ids resolve, long live Meta calls do not block the event loop (health stays at ~300 ms p95), and both live runs completed within the expected 45-120 s.

Findings (no crash bugs; performance and race observations):

1. Throughput collapse under concurrent CPU-bound requests (performance, medium). A request that takes 0.19 s serially (`GET /series`, sync handler in the threadpool) shows p50 ~35 s with 20 concurrent; `/api/health` (4 ms serial) shows p50 12 s while the pool is saturated. 8 concurrent offline investigations cost 15-54 s wall versus 8 x 1.2 s = 9.6 s serial. Cause is likely CPU contention/GIL plus numpy/sklearn BLAS/OpenMP thread oversubscription on a 96-core host: capping `OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4` roughly halved phase-1 latency (not proven as the sole cause; phase 2 did not improve in that run). Repro: `python scripts/load_test.py --pid <pid> --skip-live`. Suggested mitigation: set the thread env caps in the launch script, and/or `uvicorn --workers 2` (note the SQLite store and per-process model cache would each be per worker). Health shares the same threadpool (`apps/api/app/api/health.py`, sync `def health`), so a load balancer probe can time out during bursts.
2. Review read-modify-write race (low). `apps/api/app/db/storage.py:97-101` (`set_review`) does `get()` then `save()` of the whole JSON blob in separate connections without a transaction. Concurrent reviews are last-writer-wins (fine, and the final record was always a whole coherent record in the test), but `save()` rewrites the whole `json` column, so any other writer that updates the same case between the get and the save (for example an investigation re-save or a future field update) would be silently overwritten. Not triggered by this test. Fix idea: `BEGIN IMMEDIATE` around the read and write, or update only a review column.
3. Memory (observation). RSS grows about 570 MB across the first 8 concurrent offline investigations (204 -> 861 MB) and then plateaus (+6 MB in the next phases, +1.5 MB after the live runs). Looks like per-thread working set and cached models, not a leak, but the test was short; a longer soak was not done. `GET /api/investigations` returns every full investigation with evidence and events, so list cost grows with the case count (not stressed here).
4. During the harness runs another agent briefly broke `app.main` imports (`'APIRouter' object has no attribute 'router'` in the router mount loop), which made a server restart fail for about 2 minutes. This was transient and outside this test's scope, but it shows the router-mount loop in `apps/api/app/main.py` fails hard on a bad optional module rather than skipping it.

Not covered: sustained soak, uploads under load, `models/train`, multiple uvicorn workers.
