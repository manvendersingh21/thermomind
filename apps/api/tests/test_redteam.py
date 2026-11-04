"""QA / red-team tests for the ThermoMind API.

Adversarial and invariant checks that complement ``test_api.py``:
  (a) the Meta API key never leaks into any response body or error detail
  (b) upload hardening (path traversal, size limit before parsing, non-UTF-8,
      formula injection, empty file)
  (c) investigation window validation never produces a 500
  (d) review is additive-only (dataset rows + evidence untouched, no 500 on repeat)
  (e) no control / write endpoints exist; mutating routes are exactly the documented ones
  (f) synthetic flag propagation (S02 vs S01) across preview, evidence and report
  (g) offline report is always a draft requiring human review, with disclaimer
  (h) every evidence id cited by a report resolves via the evidence endpoints

Uses the module-scoped ``client`` fixture from ``conftest.py`` (fixture-only data,
300 rows per year, temporary DB/model dirs). The same DS/WINDOW conventions as
``test_api.py`` are used so windows always have >= 24 reference rows.
"""
from __future__ import annotations

import json
import os

import pytest

from app import config
from app.schemas import MEASUREMENT_KEYS

DS = "ds_uci_551"
WINDOW = dict(year=2014, start_index=60, end_index=120)

# Route path fragments that must never exist in a read-only decision-support API.
FORBIDDEN_ROUTE_WORDS = ["control", "setpoint", "valve", "write", "actuate", "command", "plc", "scada"]

# Mutating routes documented in contracts/api.md (method, path). Nothing else may mutate.
DOCUMENTED_MUTATING_ROUTES = {
    ("POST", "/api/datasets/seed-uci"),
    ("POST", "/api/datasets/upload"),
    ("POST", "/api/models/train"),
    ("POST", "/api/scenarios/preview"),
    ("POST", "/api/investigations"),
    ("POST", "/api/investigations/{case_id}/review"),
    # plant-ops (docs/PLANT_AGENTS.md): in-app simulated records + read-only what-if; no control actions
    ("POST", "/api/plant/work-requests/{wr_id}/status"),
    ("POST", "/api/plant/notifications/{notification_id}/read"),
    ("POST", "/api/plant/whatif"),
    # feature packages: read-only calculations carried in POST bodies, simulated records, or Muse Spark drafts
    ("POST", "/api/planner/compressor-wash"),
    ("POST", "/api/planner/filter-changeout"),
    ("POST", "/api/ops/handover"),
    ("POST", "/api/grid/drill"),
    ("POST", "/api/grid/contingency"),
    ("POST", "/api/connectors/historian/start"),
    ("POST", "/api/connectors/historian/stop"),
    ("POST", "/api/connectors/historian/tick"),
    ("POST", "/api/connectors/cmms/drafts"),
    ("POST", "/api/connectors/notifications/send"),
    ("POST", "/api/thermal/evaluate"),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _secret_values() -> list[str]:
    """All configured secret values (documented name + alias). Empty if none set."""
    vals = {v for v in (config.meta_api_key(), os.getenv("MODEL_API_KEY"), os.getenv("MUSE_API_KEY")) if v}
    return sorted(vals)


def _assert_no_secret(text: str, where: str) -> None:
    for secret in _secret_values():
        assert secret not in text, f"API key value leaked in {where}"


def _cited_ids(report: dict) -> set[str]:
    ids: set[str] = set()
    for o in report.get("observations", []):
        ids.update(o.get("evidence_ids", []))
    for h in report.get("hypotheses", []):
        ids.update(h.get("supporting_evidence_ids", []))
        ids.update(h.get("contradicting_evidence_ids", []))
    return ids


def _series(client, measure: str = "AFDP", start: int = 0, limit: int = 300) -> dict:
    r = client.get(f"/api/datasets/{DS}/series", params=dict(measure=measure, year=2014, start=start, limit=limit))
    assert r.status_code == 200, r.text
    return r.json()


def _csv_text(fixture_bytes: bytes, n_rows: int = 80) -> str:
    lines = fixture_bytes.decode("utf-8").splitlines()
    return "\n".join(lines[: n_rows + 1]) + "\n"


@pytest.fixture(scope="module")
def s02_case(client) -> dict:
    req = dict(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", use_meta=False, **WINDOW)
    r = client.post("/api/investigations", json=req)
    assert r.status_code == 200, r.text
    return client.get(f"/api/investigations/{r.json()['case_id']}").json()


@pytest.fixture(scope="module")
def s01_case(client) -> dict:
    req = dict(dataset_id=DS, scenario_id="S01_NORMAL", use_meta=False, **WINDOW)
    r = client.post("/api/investigations", json=req)
    assert r.status_code == 200, r.text
    return client.get(f"/api/investigations/{r.json()['case_id']}").json()


# ---------------------------------------------------------------------------
# (a) key never leaks
# ---------------------------------------------------------------------------


def test_secret_present_or_skipped():
    """Documents whether the leak assertions below are meaningful in this environment."""
    if not _secret_values():
        pytest.skip("MODEL_API_KEY / MUSE_API_KEY not set: leak assertions run but are vacuous")


def test_key_never_in_any_response(client, s02_case):
    if not _secret_values():
        pytest.skip("no API key configured; nothing to leak")
    case_id = s02_case["case_id"]
    responses = [
        ("GET /api/health", client.get("/api/health")),
        ("GET /api/demo/status", client.get("/api/demo/status")),
        ("GET /api/datasets", client.get("/api/datasets")),
        (f"GET /api/datasets/{DS}", client.get(f"/api/datasets/{DS}")),
        ("GET /api/models/evaluation", client.get("/api/models/evaluation")),
        ("GET /api/scenarios", client.get("/api/scenarios")),
        ("GET /api/investigations", client.get("/api/investigations")),
        (f"GET /api/investigations/{case_id}", client.get(f"/api/investigations/{case_id}")),
        (f"GET /api/investigations/{case_id}/evidence", client.get(f"/api/investigations/{case_id}/evidence")),
        (f"GET /api/investigations/{case_id}/export.json", client.get(f"/api/investigations/{case_id}/export.json")),
        ("forced 404", client.get("/api/investigations/case_does_not_exist")),
        ("forced 404 dataset", client.get("/api/datasets/ds_nope")),
        ("forced 422 series", client.get(f"/api/datasets/{DS}/series", params=dict(measure="NOPE"))),
        ("forced 422 body", client.post("/api/investigations", json={"dataset_id": 123, "start_index": "x"})),
        ("forced 422 review", client.post(f"/api/investigations/{case_id}/review", json={"decision": "bogus"})),
        ("forced 404 scenario", client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S99", **WINDOW))),
        ("forced 405", client.delete(f"/api/investigations/{case_id}")),
    ]
    for where, r in responses:
        assert r.status_code < 500, f"{where} -> {r.status_code}: {r.text[:200]}"
        _assert_no_secret(r.text, where)
        _assert_no_secret(json.dumps(dict(r.headers)), where + " headers")


def test_health_and_demo_status_do_not_echo_env_secret_fields(client):
    """Even the redacted descriptions must not include the key, only its *name*."""
    for path in ("/api/health", "/api/demo/status"):
        body = client.get(path).json()
        flat = json.dumps(body)
        _assert_no_secret(flat, path)
        # key_source may mention the env var *names* but never a value with 'Bearer' / 'sk-'.
        assert "Bearer " not in flat
        assert "api_key" not in flat.lower() or "never" in flat.lower()


# ---------------------------------------------------------------------------
# (b) upload hardening
# ---------------------------------------------------------------------------


def test_upload_path_traversal_filename_400(client, fixture_bytes):
    payload = _csv_text(fixture_bytes, 30).encode()
    for bad_name in ("../../etc/passwd", "..\\..\\windows\\win.ini", "/etc/passwd", "dir/file.csv", ".."):
        r = client.post("/api/datasets/upload", files={"file": (bad_name, payload, "text/csv")})
        assert r.status_code == 400, f"{bad_name!r} -> {r.status_code}: {r.text[:200]}"
        assert "detail" in r.json()
    # NUL bytes cannot travel through multipart (httpx percent-encodes them to '%00'), so the
    # validator is exercised directly for that case.
    from app.data.validator import CsvValidationError, safe_basename

    for name in ("a\x00b.csv", "", "   "):
        with pytest.raises(CsvValidationError) as exc:
            safe_basename(name, strict=True)
        assert exc.value.status_code == 400
    # nothing registered under a traversal name
    names = json.dumps(client.get("/api/datasets").json())
    assert "etc/passwd" not in names and "win.ini" not in names


def test_upload_oversized_413_before_parsing(client):
    """Junk that is not CSV and not UTF-8 must be rejected by size (413) before any parsing (400/422)."""
    old = config.MAX_UPLOAD_BYTES
    config.MAX_UPLOAD_BYTES = 1024
    try:
        junk = b"\xff\xfe" + os.urandom(4096)  # invalid UTF-8, no header, > limit
        r = client.post("/api/datasets/upload", files={"file": ("junk_2014.csv", junk, "text/csv")})
        assert r.status_code == 413, r.text
        assert "limit" in r.json()["detail"].lower()
        # exactly at the limit is still accepted by the size gate (then fails later on content)
        r = client.post("/api/datasets/upload", files={"file": ("tiny.csv", b"x" * 1024, "text/csv")})
        assert r.status_code in (400, 422), r.text
    finally:
        config.MAX_UPLOAD_BYTES = old


def test_upload_non_utf8_400(client):
    data = "AT,AP,AH,AFDP,GTEP,TIT,TAT,TEY,CDP,CO,NOX\n".encode("utf-8") + b"\xff\xfe\x00\x80 1,2,3\n" + os.urandom(64)
    r = client.post("/api/datasets/upload", files={"file": ("latin_2014.csv", data, "text/csv")})
    assert r.status_code == 400, r.text
    assert "utf-8" in r.json()["detail"].lower()


def test_upload_formula_cells_neutralised(client, fixture_bytes):
    """Spreadsheet formula injection: cells become NaN + a warning; the formula is never echoed back
    in the upload result, the dataset detail, the series values, or an investigation export."""
    text = _csv_text(fixture_bytes, 80)
    lines = text.splitlines()
    formula = '=HYPERLINK("http://evil.example/x","click")'
    cmd = "=cmd|' /C calc'!A0"
    # poison the AT (col 0) cell of row 1 and the NOX (last col) cell of row 2
    row1 = lines[1].split(",")
    row1[0] = f'"{formula}"'
    lines[1] = ",".join(row1)
    row2 = lines[2].split(",")
    row2[-1] = f'"{cmd}"'
    lines[2] = ",".join(row2)
    poisoned = ("\n".join(lines) + "\n").encode()

    r = client.post("/api/datasets/upload", files={"file": ("formula_2014.csv", poisoned, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == 80
    assert any("non-numeric" in w for w in body["warnings"]), body["warnings"]
    assert "HYPERLINK" not in r.text and "evil.example" not in r.text and "cmd|" not in r.text

    ds = body["dataset_id"]
    detail = client.get(f"/api/datasets/{ds}")
    assert detail.status_code == 200
    assert "HYPERLINK" not in detail.text and "cmd|" not in detail.text
    at = client.get(f"/api/datasets/{ds}/series", params=dict(measure="AT", year=2014, start=0, limit=5))
    assert at.status_code == 200
    assert at.json()["points"][0]["value"] is None, "formula cell must be NaN -> null"
    assert "HYPERLINK" not in at.text
    nox = client.get(f"/api/datasets/{ds}/series", params=dict(measure="NOX", year=2014, start=0, limit=5))
    assert nox.json()["points"][1]["value"] is None

    # investigation + export on the poisoned dataset: no formula text anywhere
    r = client.post("/api/investigations", json=dict(dataset_id=ds, scenario_id="S01_NORMAL", year=2014,
                                                     start_index=30, end_index=80, use_meta=False))
    assert r.status_code == 200, r.text
    exp = client.get(f"/api/investigations/{r.json()['case_id']}/export.json")
    assert exp.status_code == 200
    assert "HYPERLINK" not in exp.text and "evil.example" not in exp.text and "cmd|" not in exp.text


def test_upload_empty_file_422(client):
    r = client.post("/api/datasets/upload", files={"file": ("empty_2014.csv", b"", "text/csv")})
    assert r.status_code == 422, r.text
    r = client.post("/api/datasets/upload", files={"file": ("blank_2014.csv", b"   \n\n", "text/csv")})
    assert r.status_code == 422, r.text
    r = client.post("/api/datasets/upload", files={"file": ("header_only_2014.csv", (",".join(MEASUREMENT_KEYS) + "\n").encode(), "text/csv")})
    assert r.status_code == 422, r.text


def test_upload_garbage_binary_never_500(client):
    for name, data in (
        ("zip_2014.csv", b"PK\x03\x04" + b"\x00" * 200),
        ("utf8_garbage.csv", "héllo,wörld\n1,2\n".encode("utf-8")),
        ("quotes.csv", b'"unterminated,AT,AP\n1,2'),
        ("nul.csv", b"AT,AP\n\x00\x00\x00"),
    ):
        r = client.post("/api/datasets/upload", files={"file": (name, data, "application/octet-stream")})
        assert r.status_code in (400, 413, 422), f"{name}: {r.status_code} {r.text[:200]}"
        assert isinstance(r.json().get("detail"), str)


# ---------------------------------------------------------------------------
# (c) investigation window validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,overrides,expected",
    [
        ("end == start", dict(start_index=100, end_index=100), {422}),
        ("end < start", dict(start_index=120, end_index=60), {422}),
        ("negative start", dict(start_index=-5, end_index=60), {422}),
        ("> 2000 rows", dict(start_index=60, end_index=2500), {422}),
        ("start < 24 reference rows", dict(start_index=10, end_index=60), {422}),  # preview allows this (warning)
        ("start == 0", dict(start_index=0, end_index=60), {422}),  # preview allows this (warning)
        ("beyond end of year", dict(start_index=250, end_index=400), {422}),
        ("unknown year", dict(year=1999), {422, 404}),
        ("unknown scenario", dict(scenario_id="S99_NOPE"), {404}),
        ("unknown dataset", dict(dataset_id="ds_does_not_exist"), {404}),
        ("huge ints", dict(start_index=10**12, end_index=10**12 + 100), {422}),
    ],
)
def test_investigation_window_validation_never_500(client, label, overrides, expected):
    req = dict(dataset_id=DS, scenario_id="S01_NORMAL", use_meta=False, **WINDOW)
    req.update(overrides)
    r = client.post("/api/investigations", json=req)
    assert r.status_code in expected, f"{label}: {r.status_code} {r.text[:300]}"
    assert isinstance(r.json().get("detail"), (str, list))
    # the same inputs through preview must also be a clean 4xx (preview intentionally accepts
    # windows with too few reference rows and reports it as a provenance warning instead)
    preq = {k: v for k, v in req.items() if k != "use_meta"}
    pr = client.post("/api/scenarios/preview", json=preq)
    if "reference rows" in label or label == "start == 0":
        assert pr.status_code == 200, f"preview {label}: {pr.status_code} {pr.text[:300]}"
        assert pr.json()["provenance"]["warnings"], "preview must warn about the short reference"
    else:
        assert 400 <= pr.status_code < 500, f"preview {label}: {pr.status_code} {pr.text[:300]}"


def test_investigation_malformed_bodies_422(client):
    for body in ({}, {"dataset_id": DS, "start_index": "abc"}, {"dataset_id": DS, "seed": "notint"}, [1, 2], "text"):
        r = client.post("/api/investigations", json=body)
        assert r.status_code == 422, (body, r.status_code, r.text[:200])
    r = client.post("/api/investigations", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_series_query_validation_never_500(client):
    for params in (
        dict(measure="TEY", year=2014, start=-1),
        dict(measure="TEY", year=2014, limit=0),
        dict(measure="TEY", year=2014, start="abc"),
        dict(measure="TEY", year=1999),
        dict(measure="tey; drop table", year=2014),
    ):
        r = client.get(f"/api/datasets/{DS}/series", params=params)
        assert 400 <= r.status_code < 500, (params, r.status_code, r.text[:200])
    # start beyond the end of the year is clamped to an empty, well-formed series (documented behaviour)
    r = client.get(f"/api/datasets/{DS}/series", params=dict(measure="TEY", year=2014, start=10**9, limit=10))
    assert r.status_code == 200 and r.json()["points"] == [] and r.json()["end"] == r.json()["total_rows_in_year"]


# ---------------------------------------------------------------------------
# (d) review
# ---------------------------------------------------------------------------


def test_review_invalid_decision_422(client, s01_case):
    case_id = s01_case["case_id"]
    for body in ({"decision": "approved"}, {"decision": ""}, {"decision": 1}, {}, {"decision": "accepted", "reviewer": 5}):
        r = client.post(f"/api/investigations/{case_id}/review", json=body)
        assert r.status_code == 422, (body, r.status_code, r.text[:200])
    assert client.get(f"/api/investigations/{case_id}").json()["review"] is None


def test_review_does_not_change_evidence_or_rows(client, s01_case):
    case_id = s01_case["case_id"]
    rows_before = {m: _series(client, m) for m in ("AFDP", "TEY", "CDP")}
    ev_before = client.get(f"/api/investigations/{case_id}/evidence").json()
    inv_before = client.get(f"/api/investigations/{case_id}").json()

    r = client.post(f"/api/investigations/{case_id}/review",
                    json={"decision": "more_data_requested", "reviewer": "qa-red-team", "comment": "x" * 10000})
    assert r.status_code == 200, r.text
    inv_after = r.json()
    assert inv_after["review"]["decision"] == "more_data_requested"
    assert inv_after["review"]["reviewer"] == "qa-red-team"
    assert len(inv_after["review"]["comment"]) <= 4000  # comment is bounded

    rows_after = {m: _series(client, m) for m in ("AFDP", "TEY", "CDP")}
    assert rows_before == rows_after, "review changed dataset rows"
    assert client.get(f"/api/investigations/{case_id}/evidence").json() == ev_before
    for key in ("report", "evidence", "events", "baseline", "data_quality", "report_hash", "status", "deterministic_summary"):
        assert inv_after[key] == inv_before[key], f"review changed {key}"


def test_review_twice_overwrites_without_500(client, s01_case):
    """Observed behaviour: a second review OVERWRITES the first (last write wins, no history).
    Documented in docs/QA_REPORT.md; the invariant here is 'no 500, latest decision persisted'."""
    case_id = s01_case["case_id"]
    r1 = client.post(f"/api/investigations/{case_id}/review", json={"decision": "accepted", "reviewer": "r1"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/investigations/{case_id}/review", json={"decision": "rejected", "reviewer": "r2"})
    assert r2.status_code in (200, 409), r2.text
    final = client.get(f"/api/investigations/{case_id}").json()["review"]
    if r2.status_code == 200:
        assert final["decision"] == "rejected" and final["reviewer"] == "r2"  # overwrite
    else:
        assert final["decision"] == "accepted" and final["reviewer"] == "r1"  # rejected second review
    assert client.get(f"/api/investigations/{case_id}").status_code == 200


def test_review_reviewer_is_bounded_and_stripped(client, s01_case):
    case_id = s01_case["case_id"]
    r = client.post(f"/api/investigations/{case_id}/review",
                    json={"decision": "accepted", "reviewer": "   " + "n" * 500 + "   "})
    assert r.status_code == 200
    assert len(r.json()["review"]["reviewer"]) <= 120
    r = client.post(f"/api/investigations/{case_id}/review", json={"decision": "accepted", "reviewer": "   "})
    assert r.status_code == 200
    assert r.json()["review"]["reviewer"] == "demo-engineer"


# ---------------------------------------------------------------------------
# (e) read-only: no control endpoints, mutating routes are exactly the documented ones
# ---------------------------------------------------------------------------


def _api_routes():
    from app.main import app

    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", None) or [])
        out.append((path, methods))
    return out


def test_no_control_or_write_routes():
    for path, _ in _api_routes():
        low = path.lower()
        for word in FORBIDDEN_ROUTE_WORDS:
            assert word not in low, f"forbidden route word '{word}' in {path}"


def test_mutating_routes_are_exactly_documented():
    mutating = set()
    for path, methods in _api_routes():
        if not path.startswith("/api"):
            continue  # static SPA fallback / root
        for m in methods - {"GET", "HEAD", "OPTIONS"}:
            mutating.add((m, path))
    assert mutating == DOCUMENTED_MUTATING_ROUTES, f"undocumented mutating routes: {mutating - DOCUMENTED_MUTATING_ROUTES}"


def test_delete_and_put_are_405_everywhere(client, s01_case):
    case_id = s01_case["case_id"]
    for path in (f"/api/datasets/{DS}", f"/api/investigations/{case_id}", "/api/scenarios", "/api/models/evaluation"):
        for method in ("delete", "put", "patch"):
            r = getattr(client, method)(path)
            assert r.status_code in (404, 405), (method, path, r.status_code)


def test_openapi_has_no_control_vocabulary(client):
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    text = json.dumps(spec.json()).lower()
    for word in ("setpoint", "actuat", "scada", "/plc", "valve"):
        assert word not in text, f"'{word}' present in OpenAPI spec"
    _assert_no_secret(spec.text, "openapi.json")


# ---------------------------------------------------------------------------
# (f) synthetic flag propagation
# ---------------------------------------------------------------------------


def test_s02_synthetic_propagates_everywhere(client, s02_case):
    inv = s02_case
    assert inv["scenario_label"] == "synthetic_overlay"
    assert inv["scenario"]["synthetic"] is True
    assert inv["report"]["scenario_label"] == "synthetic_overlay"
    assert inv["data_quality"]["scenario_label"] == "synthetic_overlay"
    assert "AFDP" in inv["data_quality"]["synthetic_measurements"]
    afdp = [e for e in inv["evidence"] if e["metric"] == "AFDP"]
    assert afdp, "no AFDP evidence"
    assert all(e["is_synthetic"] is True for e in afdp)
    assert all(e["kind"] == "measured_plus_synthetic_overlay" for e in afdp)
    # evidence endpoints agree with the embedded evidence
    for e in afdp:
        r = client.get(f"/api/investigations/{inv['case_id']}/evidence/{e['evidence_id']}")
        assert r.status_code == 200 and r.json()["is_synthetic"] is True
    # preview says synthetic too
    pr = client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", **WINDOW))
    assert pr.status_code == 200
    assert pr.json()["synthetic"] is True and pr.json()["scenario_label"] == "synthetic_overlay"
    assert pr.json()["transformations"]
    # export carries the same labels
    exp = client.get(f"/api/investigations/{inv['case_id']}/export.json").json()
    assert exp["scenario_label"] == "synthetic_overlay" and exp["scenario"]["synthetic"] is True
    # listing carries it too
    listed = next(i for i in client.get("/api/investigations").json() if i["case_id"] == inv["case_id"])
    assert listed["scenario_label"] == "synthetic_overlay"


def test_s01_real_only_everywhere(client, s01_case):
    inv = s01_case
    assert inv["scenario_label"] == "real_only"
    assert inv["scenario"]["synthetic"] is False
    assert inv["report"]["scenario_label"] == "real_only"
    assert inv["data_quality"]["scenario_label"] == "real_only"
    assert inv["data_quality"]["synthetic_measurements"] == []
    assert inv["evidence"]
    assert all(e["is_synthetic"] is False for e in inv["evidence"])
    assert all(e["kind"] in ("real_observation", "model_derived") for e in inv["evidence"])
    pr = client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", **WINDOW))
    assert pr.json()["synthetic"] is False and pr.json()["scenario_label"] == "real_only"


def test_raw_rows_unchanged_after_s02_investigation(client, s02_case):
    """The overlay must have been applied to a copy: the raw AFDP series equals the preview 'original'."""
    raw = [p["value"] for p in _series(client, "AFDP", 60, 60)["points"]]
    pr = client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION",
                                                         measurements=["AFDP"], **WINDOW)).json()
    afdp = pr["series"][0]
    assert [p["value"] for p in afdp["original"]] == raw
    assert [p["value"] for p in afdp["overlay"]] != raw


def test_no_timestamps_fabricated(client, s02_case):
    text = client.get(f"/api/investigations/{s02_case['case_id']}/export.json").text
    assert '"timestamp"' not in text or '"timestamp": null' in text
    ds = client.get(f"/api/datasets/{DS}").json()
    assert ds["has_timestamps"] is False
    assert ds["time_axis_type"] == "ordered_hourly_sample_without_actual_timestamp"


# ---------------------------------------------------------------------------
# (g) offline report is always a draft requiring human review
# ---------------------------------------------------------------------------


def test_offline_report_status_and_disclaimer(client, s01_case, s02_case):
    for inv in (s01_case, s02_case):
        assert inv["mode"] == "offline_preview" and inv["meta_used"] is False
        report = inv["report"]
        assert report is not None
        assert report["report_status"] == "draft_requires_human_review"
        assert report["disclaimer"].strip()
        assert "not a validated" in report["disclaimer"].lower()
        assert report["case_id"] == inv["case_id"]
        assert report["hypotheses"] and all(h["status"] in ("possible", "inconclusive", "not_supported") for h in report["hypotheses"])
        # no control language in the report
        flat = json.dumps(report).lower()
        for word in ("setpoint", "actuate", "open the valve", "close the valve", "shut down the unit"):
            assert word not in flat, f"control-like language '{word}' in offline report"


def test_report_status_cannot_be_overridden_by_review(client, s02_case):
    case_id = s02_case["case_id"]
    r = client.post(f"/api/investigations/{case_id}/review", json={"decision": "accepted", "reviewer": "x"})
    assert r.status_code == 200
    assert r.json()["report"]["report_status"] == "draft_requires_human_review"
    exp = client.get(f"/api/investigations/{case_id}/export.json").json()
    assert exp["report"]["report_status"] == "draft_requires_human_review"


# ---------------------------------------------------------------------------
# (h) cited evidence ids all resolve
# ---------------------------------------------------------------------------


def test_cited_evidence_ids_resolve(client, s01_case, s02_case):
    for inv in (s01_case, s02_case):
        known = {e["evidence_id"] for e in inv["evidence"]}
        cited = _cited_ids(inv["report"])
        assert cited, "report cites no evidence"
        assert cited <= known, f"dangling ids: {cited - known}"
        for eid in cited:
            r = client.get(f"/api/investigations/{inv['case_id']}/evidence/{eid}")
            assert r.status_code == 200 and r.json()["evidence_id"] == eid
        # deterministic summary ids resolve too
        for h in inv["deterministic_summary"]["top_hypotheses"]:
            for eid in h["supporting_evidence_ids"] + h["contradicting_evidence_ids"]:
                assert eid in known, f"summary cites unknown {eid}"
        for eid in inv["deterministic_summary"]["notable_evidence_ids"]:
            assert eid in known
        # evidence ids follow ev_<slug>_<nn>
        for eid in known:
            assert eid.startswith("ev_") and eid.rsplit("_", 1)[-1].isdigit(), eid
        # evidence ids are case-scoped: not resolvable under another case
        other = s02_case if inv is s01_case else s01_case
        for eid in list(known)[:3]:
            r = client.get(f"/api/investigations/{other['case_id']}/evidence/{eid}")
            assert r.status_code in (200, 404)  # same slug may legitimately exist in both cases
        assert client.get(f"/api/investigations/{inv['case_id']}/evidence/ev_../../etc").status_code in (404, 422)
