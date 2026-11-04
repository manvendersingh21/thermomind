# ThermoMind QA / red-team report

Date: 2026-11-04. Scope: backend red-team tests (`apps/api/tests/test_redteam.py`) and a
headless-browser end-to-end pass over the built web UI (`scripts/e2e_browser.py`).
All outputs below are pasted from real runs; nothing is summarised from memory.

## 1. Backend red team

File: `apps/api/tests/test_redteam.py` (37 tests, uses the module-scoped `client`
fixture from `tests/conftest.py`: fixture-only data, 300 rows per year, temporary
DB/model dirs; same `DS` / `WINDOW` conventions as `test_api.py`).

### Commands and real output

```
$ cd apps/api && python -m pytest tests/test_redteam.py -q
37 passed, 1 warning in 6.10s

$ cd apps/api && python -m pytest -q
140 passed, 1 warning in 73.81s (0:01:13)
```

(The one warning is starlette's `anyio.abc.BlockingPortal` DeprecationWarning from
`TestClient`; it is not from ThermoMind code.)

### What is covered

| Area | Tests | Result |
|---|---|---|
| (a) API key never leaks | `test_key_never_in_any_response`, `test_health_and_demo_status_do_not_echo_env_secret_fields` | 17 responses checked (health, demo/status, datasets, dataset detail, models/evaluation, scenarios, investigations list/detail/evidence/export, forced 404 x3, forced 422 x3, forced 405): body and headers never contain the configured `MODEL_API_KEY`/`MUSE_API_KEY` value; `MUSE_API_KEY` is set in `.env`, so the assertion is live, not vacuous. `/openapi.json` also checked. |
| (b) upload hardening | `test_upload_path_traversal_filename_400`, `test_upload_oversized_413_before_parsing`, `test_upload_non_utf8_400`, `test_upload_formula_cells_neutralised`, `test_upload_empty_file_422`, `test_upload_garbage_binary_never_500` | `../../etc/passwd`, `..\..\windows\win.ini`, `/etc/passwd`, `dir/file.csv`, `..` -> 400. 4 KiB of random non-UTF-8 junk with `MAX_UPLOAD_BYTES=1024` -> 413 (size gate runs before decode/parse). Non-UTF-8 -> 400 with "UTF-8" in detail. `=HYPERLINK(...)` and `=cmd|' /C calc'!A0` cells -> 200, cells become `null`, warning "non-numeric cell(s) replaced", and the raw formula text is absent from the upload result, dataset detail, series, and an investigation export built on that dataset. Empty / whitespace-only / header-only -> 422. Zip bytes, unterminated quotes, NUL payload -> 4xx, never 500. |
| (c) window validation | `test_investigation_window_validation_never_500` (11 cases), `test_investigation_malformed_bodies_422`, `test_series_query_validation_never_500` | end==start, end<start, negative start, >2000 rows, start<24, start==0, beyond end of year, huge ints -> 422; unknown year -> 422; unknown scenario / dataset -> 404. Malformed JSON bodies -> 422. Series with bad `start`/`limit`/`measure` -> 4xx. |
| (d) review | `test_review_invalid_decision_422`, `test_review_does_not_change_evidence_or_rows`, `test_review_twice_overwrites_without_500`, `test_review_reviewer_is_bounded_and_stripped` | Invalid decisions (`approved`, empty, int, missing, bad reviewer type) -> 422 and `review` stays `null`. After a review, AFDP/TEY/CDP series, evidence list, report, events, baseline, data_quality, report_hash, status and deterministic_summary are byte-identical. Comment capped at 4000 chars, reviewer at 120 chars, blank reviewer -> `demo-engineer`. |
| (e) read-only surface | `test_no_control_or_write_routes`, `test_mutating_routes_are_exactly_documented`, `test_delete_and_put_are_405_everywhere`, `test_openapi_has_no_control_vocabulary` | No route path contains control/setpoint/valve/write/actuate/command/plc/scada. The set of non-GET `/api` routes is exactly `{POST /api/datasets/seed-uci, POST /api/datasets/upload, POST /api/models/train, POST /api/scenarios/preview, POST /api/investigations, POST /api/investigations/{case_id}/review}` (= contracts/api.md). DELETE/PUT/PATCH -> 405/404. |
| (f) synthetic propagation | `test_s02_synthetic_propagates_everywhere`, `test_s01_real_only_everywhere`, `test_raw_rows_unchanged_after_s02_investigation`, `test_no_timestamps_fabricated` | S02: `scenario_label=synthetic_overlay` on investigation, report, data_quality, list and export; `AFDP` in `synthetic_measurements`; every AFDP evidence `is_synthetic=true`, `kind=measured_plus_synthetic_overlay` (also via evidence endpoints); preview `synthetic=true` with transformations. S01: `real_only` everywhere, all evidence `is_synthetic=false`, `synthetic_measurements=[]`. Raw AFDP series == preview `original` and != `overlay`. `has_timestamps=false`, no `timestamp` value in export. |
| (g) offline report | `test_offline_report_status_and_disclaimer`, `test_report_status_cannot_be_overridden_by_review` | `report_status=draft_requires_human_review`, disclaimer "Not a validated plant safety or control system.", no control phrasing (setpoint / actuate / open|close the valve / shut down the unit) in the report; status unchanged after review and in export. |
| (h) cited evidence ids resolve | `test_cited_evidence_ids_resolve` | All ids cited by observations / hypotheses / deterministic summary / notable ids resolve via `GET .../evidence/{id}`; ids match `ev_<slug>_<nn>`; `ev_../../etc` -> 404. |

### Bugs found in app code

None that required an `xfail`. No test is marked xfail; the suite is fully green.

### Observed behaviours worth knowing (not bugs, documented so nobody re-investigates)

1. **Second review overwrites the first (last write wins, no history).**
   `app/db/storage.py::InvestigationStore.set_review` does `model_copy(update={"review": ...})` + upsert.
   Repro: `POST /review {"decision":"accepted","reviewer":"r1"}` then
   `POST /review {"decision":"rejected","reviewer":"r2"}` -> both 200, `GET` shows `rejected`/`r2`.
   The test accepts either overwrite (200) or rejection (409) and asserts the persisted state matches;
   the actual behaviour is overwrite. If an audit trail of reviews is wanted, that is a schema change
   (principal-owned).
2. **NUL bytes in upload filenames never reach the app.** httpx/multipart percent-encodes `a\x00b.csv`
   to `a%00b.csv`, which is a plain name and is accepted. `safe_basename` itself rejects NUL (tested
   directly). Likewise `..%2Fx.csv` is stored verbatim as a *label* only: the filename is never used as a
   filesystem path (`load_csv_files` takes bytes), so there is nothing to traverse.
3. **Scenario preview intentionally accepts windows with < 24 reference rows** (e.g. `start_index=0`)
   and reports it in `provenance.warnings`; only `POST /api/investigations` rejects them with 422.
   Tests encode this difference explicitly.
4. **`/series?start=<beyond year>` returns 200 with `points: []` and `end == total_rows_in_year`**
   (clamped), not 4xx. Reasonable for a chart API; tests assert the clamped shape.
5. **Upload dataset ids are content-addressed** (`ds_upload_<hash>`): re-uploading identical bytes
   under a different filename returns the same `dataset_id`. Idempotent, not a collision.

## 2. Browser end-to-end

Script: `scripts/e2e_browser.py` (Playwright 1.49.1, Chromium headless shell 131, viewport 1440x900,
`BASE` env default `http://localhost:8000`). The backend on port 8000 serving `apps/web/dist` was
already started by the principal; I did not start a server. `apps/web/dist` was built at 18:38:38 UTC
and did not change during the runs.

Install commands run:

```
pip install playwright==1.49.1 && python -m playwright install --with-deps chromium   # exit 0
```

Per page the script waits for network idle, then polls the rendered body text for up to 20 s for the
required copy (needed because React finishes rendering fetched data slightly after network idle on a
loaded machine; one earlier run missed "MAE" on `/evaluation` with a single read even though the
screenshot showed it). It records console errors (`console.error` + uncaught exceptions), failed
requests and HTTP >= 400 responses, and exits 1 on any failure.

### Real output (final run; a second consecutive run gave identical results)

```
$ python scripts/e2e_browser.py
ThermoMind browser e2e against http://localhost:8000
  health: status=ok data_ready=True model_ready=True meta_configured=True
  case: case_b1d8db08ff82 mode=meta_live status=completed scenario=S01_NORMAL synthetic=False
  synthetic case: case_760658afb3d5 mode=meta_live status=completed scenario=S03_SENSOR_INCONSISTENCY synthetic=True
- /
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /data
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /evaluation
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /replay
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /investigations
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /investigations/case_b1d8db08ff82
  - evidence drawer opened via 'ev_afdp_01' -> evidence_drawer.png
  OK  console_errors=0 failed_requests=0 missing_text=[]
- /investigations/case_760658afb3d5
  OK  console_errors=0 failed_requests=0 missing_text=[]

screenshots in /root/thermomind/docs/screenshots: data.png, evaluation.png, evidence_drawer.png, home.png, investigation.png, investigation_synthetic.png, investigations.png, replay.png
summary: 7/7 pages OK
```

Console errors: **none** on any page. Failed requests / HTTP >= 400: **none**.

Text assertions that passed: "ThermoMind" on `/`, `/replay`, `/investigations`; "CC BY" or "UCI" on
`/data`; "MAE" on `/evaluation`; "HUMAN REVIEW" (case-insensitive) on both case pages; "SYNTHETIC" on
the synthetic (S03, meta_live) case page.

### Screenshots (`docs/screenshots/`, full page, 1440 px wide)

| File | Page |
|---|---|
| `home.png` | `/` overview |
| `data.png` | `/data` data sources / provenance |
| `evaluation.png` | `/evaluation` model evaluation and trust page |
| `replay.png` | `/replay` live replay |
| `investigations.png` | `/investigations` case list |
| `investigation.png` | newest meta_live case (`case_b1d8db08ff82`, S01 real_only) |
| `investigation_synthetic.png` | newest synthetic meta_live case (`case_760658afb3d5`, S03 synthetic_overlay) |
| `evidence_drawer.png` | case page with the `ev_afdp_01` evidence drawer open |

### UI observations (not failures)

- Case pages are very tall (full-page screenshot ~12,000 px): the evidence ledger and the full agent
  event log are rendered inline. Fine for a demo; a collapsed-by-default event log would make the
  page easier to scan.
- Numbers in the "Backend / Meta status" panel on `/evaluation` are shown at full float precision
  (e.g. `holdout_mae 1.29285255580888`), unlike the formatted table above it.

## 3. Files changed (QA-owned only)

- `apps/api/tests/test_redteam.py` (new)
- `scripts/e2e_browser.py` (new)
- `docs/screenshots/*.png` (new, 8 files)
- `docs/QA_REPORT.md` (this file)

No files under `apps/api/app` or `apps/web` were modified. Nothing was committed.
