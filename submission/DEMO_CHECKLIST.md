# Demo checklist

## T-60 min: environment

- [ ] `git status` clean except intended changes; `.env` present with `MODEL_API_KEY`, never shown on screen
- [ ] `make data` done: `data/raw/uci_551/gt_2011.csv … gt_2015.csv` present, 36,733 rows total
- [ ] `make train` done: `data/models/baseline_v1.json` exists; `/evaluation` shows the metrics
- [ ] `make seed` done: cases for S01–S04 exist in the SQLite DB
- [ ] `make meta-smoke` returns ok with model id `muse-spark-1.3`; latency noted
- [ ] One **live** `S02_INTAKE_RESTRICTION` case created now (status `completed`, `mode=meta_live`); existing real case: `case_76d34565b3dc` (2026-11-04T18:32:03Z)
- [ ] One live `S03_SENSOR_INCONSISTENCY` case created; existing real case: `case_760658afb3d5` (18:33:19Z); S01: `case_b1d8db08ff82`
- [ ] `make dev` running; http://localhost:8000/api/health returns `model_ready=true`, `data_ready=true`, `meta_configured=true`
- [ ] http://localhost:8000/api/demo/status reports `ready_for_demo=true`, blockers empty
- [ ] Browser: http://localhost:5173, light UI, browser zoom 110–125 %, no stale tabs, bookmarks bar hidden
- [ ] Second screen / terminal with `make dev` logs visible to presenter only

## T-10 min: rehearsal

- [ ] Walk `/` → `/data` → `/` run S02 → `/investigations/:id` → S03 → `/evaluation` → `/replay` → review in under 3:00 (docs/DEMO_SCRIPT.md)
- [ ] Confirm badges visible: REAL PUBLIC DATA, SYNTHETIC OVERLAY, MODEL-DERIVED, HUMAN REVIEW REQUIRED
- [ ] Confirm the x-axis reads `2014 • sample #…` and no date appears anywhere for UCI rows
- [ ] Confirm the agent trace shows at least one `tool_call` / `tool_result` pair and a `report_accepted` (or an honest `needs_review`)
- [ ] Decide fallback: pre-created live case ids above; offline preview labelled "not a Meta inference" if the API fails

## During the demo

- [ ] Say "synthetic overlay" out loud when running S02/S03/S04
- [ ] Say "draft, requires human review" when the report appears
- [ ] Never claim detection accuracy, avoided downtime, customers or sales
- [ ] If a request errors, show the error and move to the fallback; do not reload blindly

## After the demo

- [ ] Export the live case JSON (`/api/investigations/{id}/export.json`) and keep it with the submission
- [ ] Screenshots captured at `docs/screenshots/{home,data,investigation,evaluation,replay}.png`
- [ ] Record the live smoke-test fields in docs/EVALUATION.md
- [ ] Stop `make dev`; confirm `.env` was not committed
- [ ] Demo video at `submission/video/thermomind_demo.mp4`, ≤ 3:00

## Late features (optional extra beats)

- [ ] `/propose`: say "agents confer, a human decides, nothing is executed"; `/watchdog`: say "simulated auxiliaries; auto-execution only inside the simulation"; `/twin` and `/executive` are model-derived views of demo data

## Submit in the last 20 minutes

1. [ ] Upload `submission/video/thermomind_demo.mp4` to YouTube (unlisted or public); open the link logged out to confirm it plays.
2. [ ] Fill `<FILL by owner>` team field in `submission/FORM_ANSWERS.md` (names, roles, contact email).
3. [ ] Paste the YouTube link into the demo video field.
4. [ ] Confirm https://github.com/manvendersingh21/thermomind is public and the latest commit is pushed.
5. [ ] Confirm `.env` is not in the repo and no key appears in `git grep -i "sk-"`.
6. [ ] Confirm README banner and docs/EVALUATION.md numbers match FORM_ANSWERS.md (MAE 1.293, 531 and 52 tests).
7. [ ] Paste each field from `submission/FORM_ANSWERS.md`; check word limits shown in the form.
8. [ ] Select track: Startup; live demo field: "Not deployed; reproducible locally (README)".
9. [ ] Re-read once for any accuracy, savings or adoption claim; remove it if present.
10. [ ] Submit before 9 PM ET, then save the confirmation screenshot.
