# Final verification record (2026-11-05, 01:22–01:35 UTC)

All outputs below were produced by running the code in this repository on the build machine.

| Check | Result |
|---|---|
| Full backend suite (`cd apps/api && python -m pytest -q`) | 547 passed, 1 warning in 446.79s |
| Late packages + simulator (`tests/test_deliberation.py tests/test_watchdog.py tests/test_late_packages_fuzz.py tests/test_simulator.py tests/test_collab.py tests/test_executive.py`) | 98 passed, 1 warning in 29.97s |
| Web unit tests (`npm run test`) | 9 files, 52 tests passed |
| Web typecheck (`tsc --noEmit`) | no errors |
| Browser sweep, 24 routes at 1440×900 (Playwright) | 24/24 OK, 0 console errors |
| Clean clone of the pushed repository (`git clone` → venv → `scripts/train.py` → `pytest tests/test_api.py tests/test_simulator.py tests/test_ingest.py` → `npm run typecheck` → `npm run build`) | trained; 57 passed; typecheck clean; built in 14.48s |
| Live Muse Spark investigations stored (S01–S04) | 4, zero validator errors (docs/EVALUATION.md) |
| Live deliberations stored on the S02 demo case | 7 |
| Watchdog API live (`/api/watchdog/state`) | auxiliaries, detections, events, executions, honesty_statement present |
| Simulator live (`/api/simulator/state`) | running; intake-fouling fault raised AFDP from 3.9 to 17.6 mbar within the first simulated hour |
| Final video (`submission/video/thermomind_demo.mp4`) | 173.4 s, 1920×1080 h264 + aac |

Independent reviews that ran on the late packages before this record: an adversarial review-and-fix pass (deliberation, watchdog, collab, executive: control-wording scan, fuzzing with NaN/inf/strings, UI check with screenshots) and a simulator verifier (physics directions for hot-day and intake-fouling faults, energy closure, API flow, provenance flags, route-word check). Their fixes are committed.

Not done, by design or by circumstance: no cloud deployment; Docker file untested; the physics simulator is a 0-D model finished in the last hour and labelled experimental; the YouTube upload and the submission form require the owner's accounts.
