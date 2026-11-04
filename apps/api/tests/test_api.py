"""HTTP API tests (TestClient, fixture-only data: 300 rows per year)."""
from __future__ import annotations

import json
import math

import pytest

from app import config, services
from app.schemas import MEASUREMENT_KEYS

DS = "ds_uci_551"
WINDOW = dict(year=2014, start_index=60, end_index=120)


def _assert_no_key(body: str) -> None:
    key = config.meta_api_key()
    if key:
        assert key not in body, "API key leaked in response body"


# ---------------------------------------------------------------------------
# health / demo
# ---------------------------------------------------------------------------


def test_health_shape_and_no_key_leak(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    for k in ("status", "version", "build", "data_ready", "model_ready", "meta_configured", "meta_model", "meta_base_url"):
        assert k in body
    assert body["status"] in ("ok", "degraded")
    assert body["data_ready"] is True
    assert body["meta_configured"] == config.meta_configured()
    _assert_no_key(r.text)


def test_demo_status_no_key_leak(client):
    r = client.get("/api/demo/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"data", "model", "meta", "backend", "scenarios", "build", "ready_for_demo", "blockers"}
    assert body["data"]["ready"] is True
    assert "configured" in body["meta"]
    _assert_no_key(r.text)


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------


def test_datasets_list_and_detail(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    ids = [d["dataset_id"] for d in r.json()]
    assert DS in ids
    summary = next(d for d in r.json() if d["dataset_id"] == DS)
    assert summary["has_timestamps"] is False
    assert summary["columns"] == MEASUREMENT_KEYS
    assert summary["time_axis_type"] == "ordered_hourly_sample_without_actual_timestamp"

    r = client.get(f"/api/datasets/{DS}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["has_timestamps"] is False
    assert len(detail["measurements"]) == 11
    assert detail["rows_per_year"]["2014"] == 300
    assert detail["source_files"] and detail["provenance_notes"]
    assert detail["source_license"] == "CC-BY-4.0"


def test_seed_uci_idempotent(client):
    r1 = client.post("/api/datasets/seed-uci")
    r2 = client.post("/api/datasets/seed-uci")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["dataset_id"] == DS
    assert r1.json()["row_count"] == r2.json()["row_count"]


def test_series_bounds_and_downsampling(client):
    r = client.get(f"/api/datasets/{DS}/series", params=dict(measure="AFDP", year=2014, start=10, limit=50))
    assert r.status_code == 200
    body = r.json()
    assert body["start"] == 10 and body["end"] == 60
    assert body["total_rows_in_year"] == 300
    assert body["downsample_factor"] == 1
    assert [p["row_index"] for p in body["points"]] == list(range(10, 60))
    assert body["provenance_kind"] == "real_observation"
    assert body["synthetic"] is False
    assert all(p["expected"] is None for p in body["points"])

    # clamped at the end of the year
    r = client.get(f"/api/datasets/{DS}/series", params=dict(measure="TEY", year=2014, start=290, limit=500))
    assert r.status_code == 200
    assert r.json()["end"] == 300 and len(r.json()["points"]) == 10

    # downsampling: ask for more points than MAX_SERIES_POINTS allows
    old = config.MAX_SERIES_POINTS
    config.MAX_SERIES_POINTS = 100
    try:
        r = client.get(f"/api/datasets/{DS}/series", params=dict(measure="TEY", year=2014, start=0, limit=300))
        assert r.status_code == 200
        assert r.json()["downsample_factor"] == 3
        assert len(r.json()["points"]) <= 100
    finally:
        config.MAX_SERIES_POINTS = old

    r = client.get(f"/api/datasets/{DS}/series", params=dict(measure="NOPE", year=2014))
    assert r.status_code == 422


def test_series_include_expected_is_model_derived(client, trained_model):
    r = client.get(
        f"/api/datasets/{DS}/series",
        params=dict(measure="TEY", year=2014, start=0, limit=20, include_expected="true"),
    )
    assert r.status_code == 200
    pts = r.json()["points"]
    if trained_model is None:
        assert all(p["expected"] is None for p in pts)
    else:
        assert all(p["expected"] is not None and math.isfinite(p["expected"]) for p in pts)
        # observed values are untouched real observations
        assert r.json()["provenance_kind"] == "real_observation"


def test_upload_fixture_ok(client, fixture_bytes):
    r = client.post("/api/datasets/upload", files={"file": ("gt_2014_sample300.csv", fixture_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == 300
    assert body["columns"] == MEASUREMENT_KEYS
    assert body["source"] == "USER_UPLOAD"
    assert len(body["sha256"]) == 64
    r = client.get(f"/api/datasets/{body['dataset_id']}")
    assert r.status_code == 200
    assert r.json()["has_timestamps"] is False


def test_upload_missing_column_422(client, fixture_bytes):
    text = fixture_bytes.decode("utf-8")
    lines = text.splitlines()
    header = lines[0].split(",")
    drop = header.index("TIT")
    bad = "\n".join(",".join(c for i, c in enumerate(l.split(",")) if i != drop) for l in lines[:50])
    r = client.post("/api/datasets/upload", files={"file": ("no_tit.csv", bad.encode(), "text/csv")})
    assert r.status_code == 422
    assert "TIT" in r.json()["detail"]


def test_upload_oversized_413(client, fixture_bytes):
    old = config.MAX_UPLOAD_BYTES
    config.MAX_UPLOAD_BYTES = 1024
    try:
        r = client.post("/api/datasets/upload", files={"file": ("big_2014.csv", fixture_bytes, "text/csv")})
        assert r.status_code == 413
    finally:
        config.MAX_UPLOAD_BYTES = old


def test_unknown_dataset_404(client):
    assert client.get("/api/datasets/ds_nope").status_code == 404
    assert client.get("/api/datasets/ds_nope/series", params=dict(measure="TEY")).status_code == 404


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def test_model_evaluation(client, trained_model):
    r = client.get("/api/models/evaluation")
    if trained_model is None:
        assert r.status_code == 404
        return
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "TEY" and body["target_unit"] == "MWh"
    assert math.isfinite(body["holdout"]["mae"]) and body["holdout"]["n"] > 0
    assert "TEY" not in body["features"]


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------


def test_scenarios_list_has_synthetic_flags(client):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    items = r.json()
    by_id = {s["scenario_id"]: s for s in items}
    assert "S01_NORMAL" in by_id and "S02_INTAKE_RESTRICTION" in by_id
    assert by_id["S01_NORMAL"]["synthetic"] is False
    assert by_id["S02_INTAKE_RESTRICTION"]["synthetic"] is True
    assert all("synthetic" in s and "expected_behavior" in s for s in items)


def test_preview_s02_original_unchanged(client):
    req = dict(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", measurements=["AFDP", "TEY"], **WINDOW)
    r = client.post("/api/scenarios/preview", json=req)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["synthetic"] is True and body["scenario_label"] == "synthetic_overlay"
    assert body["seed"] == 42
    assert body["transformations"]
    afdp = next(s for s in body["series"] if s["measure"] == "AFDP")
    orig = [p["value"] for p in afdp["original"]]
    over = [p["value"] for p in afdp["overlay"]]
    assert len(orig) == 60 and len(over) == 60
    assert orig != over

    # original must equal the raw series endpoint (raw rows never mutated)
    s = client.get(f"/api/datasets/{DS}/series", params=dict(measure="AFDP", year=2014, start=60, limit=60)).json()
    assert [p["value"] for p in s["points"]] == orig
    assert [p["row_index"] for p in s["points"]] == [p["row_index"] for p in afdp["original"]]

    # calling preview twice does not drift (overlay applied to a copy each time)
    r2 = client.post("/api/scenarios/preview", json=req)
    assert [p["value"] for p in next(s for s in r2.json()["series"] if s["measure"] == "AFDP")["original"]] == orig


def test_preview_s01_overlay_equals_original_and_validation(client):
    r = client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", **WINDOW))
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic"] is False and body["scenario_label"] == "real_only"
    for s in body["series"]:
        assert [p["value"] for p in s["original"]] == [p["value"] for p in s["overlay"]]
    # too-short window -> 422; out-of-range -> 422; unknown scenario -> 404
    assert client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", year=2014, start_index=10, end_index=20)).status_code == 422
    assert client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", year=2014, start_index=200, end_index=400)).status_code == 422
    assert client.post("/api/scenarios/preview", json=dict(dataset_id=DS, scenario_id="S99", **WINDOW)).status_code == 404


# ---------------------------------------------------------------------------
# investigations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def offline_case(client) -> dict:
    req = dict(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", use_meta=False, **WINDOW)
    r = client.post("/api/investigations", json=req)
    assert r.status_code == 200, r.text
    created = r.json()
    inv = client.get(f"/api/investigations/{created['case_id']}").json()
    return inv


def _cited_ids(report: dict) -> set[str]:
    ids: set[str] = set()
    for o in report.get("observations", []):
        ids.update(o.get("evidence_ids", []))
    for h in report.get("hypotheses", []):
        ids.update(h.get("supporting_evidence_ids", []))
        ids.update(h.get("contradicting_evidence_ids", []))
    return ids


def test_post_investigation_offline(client, offline_case, trained_model):
    inv = offline_case
    assert inv["case_id"].startswith("case_")
    assert inv["status"] in ("completed", "needs_review")
    assert inv["mode"] == "offline_preview"
    assert inv["meta_used"] is False
    assert inv["scenario_label"] == "synthetic_overlay"
    assert inv["scenario"]["synthetic"] is True
    assert inv["window"] == {"source_year": 2014, "start": 60, "end": 120}
    assert inv["reference"] == {"source_year": 2014, "start": 0, "end": 60}
    assert inv["evidence"], "expected deterministic evidence"
    assert inv["data_quality"]["scenario_label"] == "synthetic_overlay"
    assert inv["deterministic_summary"]["top_hypotheses"]
    if trained_model is not None:
        assert inv["model_version"] == trained_model.version
        assert inv["baseline"] is not None
    else:
        assert inv["model_version"] is None and inv["baseline"] is None
        assert all(e["kind"] != "model_derived" for e in inv["evidence"])
    report = inv["report"]
    assert report is not None
    assert report["report_status"] == "draft_requires_human_review"
    assert report["scenario_label"] == "synthetic_overlay"
    assert report["case_id"] == inv["case_id"]

    # every cited evidence id resolves
    known = {e["evidence_id"] for e in inv["evidence"]}
    cited = _cited_ids(report)
    assert cited, "report cites no evidence"
    assert cited <= known
    for eid in cited:
        r = client.get(f"/api/investigations/{inv['case_id']}/evidence/{eid}")
        assert r.status_code == 200 and r.json()["evidence_id"] == eid
    r = client.get(f"/api/investigations/{inv['case_id']}/evidence")
    assert r.status_code == 200 and len(r.json()) == len(inv["evidence"])
    assert client.get(f"/api/investigations/{inv['case_id']}/evidence/ev_nope_99").status_code == 404

    # list newest first includes it
    r = client.get("/api/investigations")
    assert r.status_code == 200
    assert r.json()[0]["case_id"] == inv["case_id"]
    _assert_no_key(json.dumps(inv))


def test_investigation_reference_too_short_422(client):
    r = client.post("/api/investigations", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", year=2014, start_index=10, end_index=60, use_meta=False))
    assert r.status_code == 422
    r = client.post("/api/investigations", json=dict(dataset_id="ds_nope", scenario_id="S01_NORMAL", use_meta=False, **WINDOW))
    assert r.status_code == 404
    r = client.post("/api/investigations", json=dict(dataset_id=DS, scenario_id="S99", use_meta=False, **WINDOW))
    assert r.status_code == 404


def test_review_transition_and_data_unchanged(client, offline_case):
    case_id = offline_case["case_id"]
    before = client.get(f"/api/datasets/{DS}/series", params=dict(measure="AFDP", year=2014, start=60, limit=60)).json()
    r = client.post(f"/api/investigations/{case_id}/review", json={"decision": "accepted", "reviewer": "eng-1", "comment": "looks consistent"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review"]["decision"] == "accepted"
    assert body["review"]["reviewer"] == "eng-1"
    assert body["review"]["ts_utc"].endswith("Z")
    assert body["report"] == offline_case["report"]
    assert body["evidence"] == offline_case["evidence"]
    assert client.get(f"/api/investigations/{case_id}").json()["review"]["decision"] == "accepted"
    after = client.get(f"/api/datasets/{DS}/series", params=dict(measure="AFDP", year=2014, start=60, limit=60)).json()
    assert before == after
    assert client.post(f"/api/investigations/{case_id}/review", json={"decision": "bogus"}).status_code == 422


def test_export_json_download(client, offline_case):
    case_id = offline_case["case_id"]
    r = client.get(f"/api/investigations/{case_id}/export.json")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert case_id in r.headers["content-disposition"]
    body = json.loads(r.text)
    assert body["case_id"] == case_id
    assert body["report"]["report_status"] == "draft_requires_human_review"


def test_unknown_case_404(client):
    assert client.get("/api/investigations/case_000000000000").status_code == 404
    assert client.get("/api/investigations/case_000000000000/evidence").status_code == 404
    assert client.get("/api/investigations/case_000000000000/export.json").status_code == 404
    r = client.post("/api/investigations/case_000000000000/review", json={"decision": "rejected"})
    assert r.status_code == 404
    assert r.json()["detail"]


def test_investigation_s01_real_only(client):
    r = client.post("/api/investigations", json=dict(dataset_id=DS, scenario_id="S01_NORMAL", use_meta=False, **WINDOW))
    assert r.status_code == 200, r.text
    inv = client.get(f"/api/investigations/{r.json()['case_id']}").json()
    assert inv["scenario_label"] == "real_only"
    assert inv["scenario"]["synthetic"] is False
    assert all(e["is_synthetic"] is False for e in inv["evidence"])
    assert inv["report"]["scenario_label"] == "real_only"


def test_s02_overlay_reaches_evidence_engine(offline_case):
    """Regression: the pipeline must analyze the scenario-applied copy, not the raw window.

    With the synthetic AFDP ramp applied, AFDP evidence must be marked synthetic and the
    top deterministic hypothesis must not be 'unknown' with nothing notable.
    """
    ev = {e["evidence_id"]: e for e in offline_case["evidence"]}
    assert ev["ev_afdp_01"]["is_synthetic"] is True
    assert ev["ev_afdp_01"]["kind"] == "measured_plus_synthetic_overlay"
    notable = [e for e in offline_case["evidence"] if "notable_deviation" in e["flags"]]
    assert notable, "S02 overlay produced no notable evidence — overlay not applied?"
    assert offline_case["report"]["hypotheses"][0]["key"] == "intake_restriction"
