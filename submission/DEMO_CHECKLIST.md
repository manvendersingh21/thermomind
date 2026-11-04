# Demo checklist

## T-60 min: environment

- [ ] `git status` clean except intended changes; `.env` present with `MODEL_API_KEY`, never shown on screen
- [ ] `make data` done: `data/raw/uci_551/gt_2011.csv … gt_2015.csv` present, 36,733 rows total
- [ ] `make train` done: `data/models/baseline_v1.json` exists; `/evaluation` shows the metrics
- [ ] `make seed` done: cases for S01–S04 exist in the SQLite DB
- [ ] `make meta-smoke` returns ok with model id `muse-spark-1.3`; latency noted
- [ ] One **live** `S02_INTAKE_RESTRICTION` case created now (status `completed`, `mode=meta_live`); case id written down: `________`
- [ ] One live `S03_SENSOR_INCONSISTENCY` case created; case id: `________`
- [ ] `make dev` running; http://localhost:8000/api/health returns `model_ready=true`, `data_ready=true`, `meta_configured=true`
- [ ] http://localhost:8000/api/demo/status reports `ready_for_demo=true`, blockers empty
- [ ] Browser: http://localhost:5173, zoom 110–125 %, dark/light theme chosen, no stale tabs, bookmarks bar hidden
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
