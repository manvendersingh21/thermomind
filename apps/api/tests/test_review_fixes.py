"""Regression tests for the independent-review findings (validator, tool leaks, NaN persistence,
offline severity, time budget, truncation, S03 window, train guard, upload persistence)."""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import config, services
from app.agent import orchestrator
from app.agent._fake_case import CASE_ID, make_fake_analysis
from app.agent.meta_client import ChatResult
from app.agent.orchestrator import TRUNCATED_PLACEHOLDER, build_offline_report, run_investigation
from app.agent.report_validator import validate_report
from app.agent.tools import TOOL_SPECS, ToolRunner
from app.schemas import UCI_SOURCE_ID, Evidence, SampleRange
from tests.test_agent_mock import KNOWN, LABEL, STANDARD_CALLS, FakeMetaClient, good_report, text_msg, tool_call_msg

DS = "ds_uci_551"
WINDOW = dict(year=2014, start_index=60, end_index=120)


def _errors(**overrides) -> list[str]:
    report, errors = validate_report(good_report(**overrides), CASE_ID, KNOWN, LABEL)
    assert (report is None) == bool(errors)
    return errors


# ----------------------------------------------------------------------------- 1. validator
REJECT = [
    "Operators should shut the unit down immediately.",
    "Shutdown the unit.",
    "Reduce turbine load to 80% until the filter is replaced.",
    "Stop the turbine and isolate the fuel supply.",
    "Lower the TIT to 1060 C.",
    "Close the IGVs by 5 degrees.",
    "De-rate the unit and switch off the compressor wash pump.",
    "Raise the firing temperature.",
    "Reset the protection relay and restart the GT.",
    "Trip the unit.",
    "Bypass the filter interlock.",
    "Override the protection on the GT.",
    "Ramp down the load.",
]
DATES = [
    "Event occurred on 05.03.2014.",
    "Event occurred on 05/03/2014.",
    "Event occurred in March 2014.",
    "Recorded at 14:30 on the day.",
    "Deviation started around 2014-3-5.",
]
ACCEPT = [
    "Review the trip logs and shutdown records, if available.",
    "No shutdown or trip is recorded in the dataset.",
    "Check whether the filter bypass damper position is recorded.",
    "No override of protection settings is implied.",
    "Higher ambient temperature reduces output.",
    "An intake restriction tends to reduce mass flow and output.",
    "A decrease in output is visible in source_year 2014, sample #1250.",
    "Lower ambient temperature explains part of the TEY rise.",
    "AFDP started rising at sample #1230 while TEY stayed flat.",
    "Confirm whether the unit was operating at reduced load.",
    "Source year 2014, samples 1200-1320.",
]


@pytest.mark.parametrize("text", REJECT)
def test_validator_rejects_imperative_control_forms(text):
    errors = _errors(summary=text)
    assert any(e.startswith("unsafe_instruction") for e in errors), (text, errors)


@pytest.mark.parametrize("text", DATES)
def test_validator_rejects_date_and_time_forms(text):
    errors = _errors(summary=text)
    assert any(e.startswith("fabricated_date") for e in errors), (text, errors)


@pytest.mark.parametrize("text", ACCEPT)
def test_validator_accepts_read_only_text(text):
    assert _errors(summary=text, engineer_review_checks=[text]) == []


def test_validator_scans_key_name_and_forces_data_source():
    rep = good_report(data_source="Plant historian export 05.03.2014 14:00")
    report, errors = validate_report(rep, CASE_ID, KNOWN, LABEL)
    assert errors == [] and report.data_source == UCI_SOURCE_ID
    hyps = good_report()["hypotheses"]
    hyps[0]["key"] = "reduce load to 80% and isolate fuel"
    errors = _errors(hypotheses=hyps)
    assert any("hypotheses[0].key" in e for e in errors)
    hyps = good_report()["hypotheses"]
    hyps[1]["name"] = "Trip the unit"
    assert any("hypotheses[1].name" in e for e in _errors(hypotheses=hyps))


def test_validator_inline_evidence_ids_must_be_known():
    errors = _errors(summary="AFDP rose [ev_afdp_01] and [ev_fake_99] confirms it.")
    assert any("ev_fake_99" in e and "inline" in e for e in errors)
    assert not any("ev_afdp_01" in e for e in errors)
    hyps = good_report()["hypotheses"]
    hyps[0]["rationale"] = "see ev_made_up_01"
    assert any("ev_made_up_01" in e for e in _errors(hypotheses=hyps))


# ----------------------------------------------------------------------------- 1f. orchestrator ids / required tools
def test_orchestrator_accepts_only_ids_returned_by_tools():
    analysis = make_fake_analysis(synthetic=True)
    calls = [("get_baseline_comparison", {}), ("get_data_quality", {}),
             ("evaluate_hypothesis", {"hypothesis_key": "operating_condition"})]
    # ev_afdp_01 exists in the case but no tool in this run returned it
    cites_unreturned = good_report()
    restricted = good_report(
        summary="TEY residual negative [ev_tey_residual_01]; CDP flat [ev_cdp_01].",
        observations=[{"statement": "TEY residual negative.", "evidence_ids": ["ev_tey_residual_01"]}],
        hypotheses=[{"name": "Sensor issue", "key": "sensor_issue", "rank": 1, "status": "inconclusive",
                     "supporting_evidence_ids": ["ev_cdp_01"], "contradicting_evidence_ids": ["ev_tey_residual_01"]}])
    client = FakeMetaClient([tool_call_msg(calls), text_msg(cites_unreturned), text_msg(restricted)])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed", out.validation_errors
    rewrite_prompt = client.calls[2]["messages"][-1]["content"]
    assert "ev_afdp_01" in rewrite_prompt and "unknown evidence_ids" in rewrite_prompt


def test_orchestrator_requires_baseline_quality_and_hypothesis_tools():
    analysis = make_fake_analysis(synthetic=True)
    only_baseline = tool_call_msg([("get_baseline_comparison", {})])
    client = FakeMetaClient([only_baseline, text_msg(good_report()), text_msg(good_report())])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "needs_review" and out.report is None
    nudge = client.calls[2]["messages"][-1]["content"]
    assert "get_data_quality" in nudge and "evaluate_hypothesis" in nudge
    assert any("required tools not called" in e for e in out.validation_errors)
    assert len(client.calls) == 3  # one nudge round only, no rewrite (it cannot call tools)


# ----------------------------------------------------------------------------- truncation (coordinator item)
class _ScriptedClient:
    model = "fake-muse"
    configured = True
    timeout_s = 1.0

    def __init__(self, script: list[tuple[dict, str]], delay_s: float = 0.0):
        self.script = list(script)
        self.calls: list[list[dict]] = []
        self.delay_s = delay_s

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append([dict(m) for m in messages])
        if self.delay_s:
            time.sleep(self.delay_s)
        msg, finish = self.script.pop(0)
        return ChatResult(message=msg, usage={}, latency_ms=1, model=self.model, finish_reason=finish)


def test_truncated_first_answer_is_never_echoed_empty_and_triggers_rewrite():
    analysis = make_fake_analysis(synthetic=True)
    client = _ScriptedClient([
        (tool_call_msg(STANDARD_CALLS), "tool_calls"),
        ({"role": "assistant", "content": None}, "length"),
        (text_msg(good_report()), "stop"),
    ])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed", out.validation_errors
    for sent in client.calls:
        for m in sent:
            if m["role"] == "assistant":
                assert m.get("content") or m.get("tool_calls"), m
    assert any(m.get("content") == TRUNCATED_PLACEHOLDER for m in client.calls[2])
    assert "cut off; answer with compact JSON only" in client.calls[2][-1]["content"]


def test_truncated_very_first_response_is_nudged_not_failed():
    analysis = make_fake_analysis(synthetic=True)
    client = _ScriptedClient([
        ({"role": "assistant", "content": None}, "length"),
        (tool_call_msg(STANDARD_CALLS), "tool_calls"),
        (text_msg(good_report()), "stop"),
    ])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed", out.validation_errors


# ----------------------------------------------------------------------------- 7. time budget
def test_time_budget_stops_tool_loop(monkeypatch):
    monkeypatch.setattr(orchestrator, "TIME_BUDGET_S", 1.0)
    client = _ScriptedClient([(tool_call_msg(STANDARD_CALLS), "tool_calls")] * 5, delay_s=0.6)
    client.timeout_s = 0.5
    out = run_investigation(make_fake_analysis(synthetic=True), LABEL, client)
    assert out.status == "needs_review" and out.report is None
    assert len(client.calls) == 1
    errs = [e for e in out.events if e.kind == "error"]
    assert errs and errs[0].summary.startswith("time budget exhausted")
    assert out.validation_errors[0].startswith("time budget exhausted")


def test_meta_client_no_sdk_retries_and_single_connection_retry(monkeypatch):
    import httpx
    import openai

    from app.agent import meta_client as mc

    monkeypatch.setattr(mc, "CONNECTION_RETRY_DELAY_S", 0.0)
    client = mc.MetaClient(api_key="sk-test-not-a-real-key-123456", base_url="http://127.0.0.1:9/v1",
                           model="m", timeout_s=5)
    assert client._client.max_retries == 0
    req = httpx.Request("POST", "http://127.0.0.1:9/v1/chat/completions")
    good = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content="pong",
                                                                            tool_calls=None),
                                                    finish_reason="stop")], usage=None, model="m")
    attempts = []

    def flaky(**kw):
        attempts.append(1)
        if len(attempts) == 1:
            raise openai.APIConnectionError(request=req)
        return good

    monkeypatch.setattr(client._client.chat.completions, "create", flaky)
    assert client.chat([{"role": "user", "content": "x"}], None, 10).message["content"] == "pong"
    assert len(attempts) == 2

    attempts.clear()

    def slow(**kw):
        attempts.append(1)
        raise openai.APITimeoutError(request=req)

    monkeypatch.setattr(client._client.chat.completions, "create", slow)
    with pytest.raises(mc.MetaClientError):
        client.chat([{"role": "user", "content": "x"}], None, 10)
    assert len(attempts) == 1  # timeouts are not retried


# ----------------------------------------------------------------------------- 9. tool result truncation
def test_tool_message_truncation_is_valid_json(monkeypatch):
    monkeypatch.setattr(orchestrator, "MAX_TOOL_RESULT_CHARS", 50)
    msg = orchestrator._tool_message("c1", {"blob": "x" * 500})
    body = json.loads(msg["content"])
    assert body["truncated"] is True and len(body["partial"]) == 50


def test_segment_evidence_lists_at_most_ten_segments():
    from app.analytics.evidence import _segment_evidence
    from app.analytics.scenarios import ScenarioResult

    rng = np.random.default_rng(0)
    n = 300
    wf = pd.DataFrame({k: rng.normal(10, 0.01, n) for k in ("CDP", "TEY", "AFDP", "TIT", "GTEP")})
    wf.loc[list(range(5, n, 20)), "CDP"] += 5.0  # 15 isolated spikes
    sc = ScenarioResult(scenario_id="S01_NORMAL", synthetic=False, seed=42, frame=wf)
    w = SampleRange(source_year=2014, start=0, end=n)
    ev = _segment_evidence("ev_cdp_02", "c", "CDP", wf, w, w, sc, ["TEY", "AFDP", "TIT", "GTEP"])
    assert ev.values["total_segments"] == 15 and len(ev.values["segments"]) == 10
    assert "+5 more" in ev.computation


# ----------------------------------------------------------------------------- 4/5. offline severity + notable
def _ev(eid: str, z: float, flags: list[str], dq: str = "pass") -> Evidence:
    w = SampleRange(source_year=2014, start=0, end=10)
    return Evidence(evidence_id=eid, case_id=CASE_ID, kind="real_observation", metric="CDP", unit="u",
                    title="t", sample_range=w, method="m", computation="c", z_score=z, flags=flags,
                    observed_stat=1.0, comparison_stat=1.0,
                    data_quality=dq)


def test_offline_severity_uses_flags_not_raw_z():
    a = make_fake_analysis(synthetic=False)
    a.evidence = [_ev("ev_cdp_02", 9.0, ["coincident_with_other_sensors"]), _ev("ev_at_01", 1.0, [])]
    assert build_offline_report(a, "real_only").severity == "informational"
    a.evidence = [_ev("ev_cdp_02", 0.5, ["isolated_single_sensor"])]
    assert build_offline_report(a, "real_only").severity == "review"
    a.evidence = [_ev("ev_ood_01", 0.0, ["out_of_training_range"])]
    assert build_offline_report(a, "real_only").severity == "review"


def test_deterministic_summary_notable_rule():
    a = SimpleNamespace(hypothesis_evals={}, evidence=[
        _ev("ev_big_z", 5.0, ["coincident_with_other_sensors"]),
        _ev("ev_flagged", 0.1, ["notable_deviation"]),
        _ev("ev_gpu", 3.0, ["gpu_second_opinion", "baselines_agree"]),
        _ev("ev_warn", 0.0, [], dq="warn"),
    ])
    assert services._deterministic_summary(a)["notable_evidence_ids"] == ["ev_flagged", "ev_warn"]


# ----------------------------------------------------------------------------- 11. S03 window
def test_s03_offset_is_middle_third_for_any_window_length():
    from app.analytics.scenarios import apply_scenario

    for n, rows in ((120, [40, 80]), (30, [10, 20]), (24, [8, 16])):
        frame = pd.DataFrame({"CDP": np.full(n, 11.0), "TEY": np.full(n, 130.0)})
        res = apply_scenario(frame, "S03_SENSOR_INCONSISTENCY", 42)
        assert res.transformations[0].params["rows"] == rows
        diff = res.frame["CDP"].to_numpy() - 11.0
        assert np.all(np.abs(diff[rows[0]:rows[1]] - 1.5) < 0.3) and np.all(diff[:rows[0]] == 0)


# ----------------------------------------------------------------------------- 12. model mtime
def test_model_mtime_tracks_json_and_joblib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    (tmp_path / "baseline_v1.joblib").write_bytes(b"x")
    (tmp_path / "baseline_v1.json").write_text("{}")
    os.utime(tmp_path / "baseline_v1.joblib", (1000, 1000))
    os.utime(tmp_path / "baseline_v1.json", (2000, 2000))
    assert services._model_files_mtime() == 2000


# ----------------------------------------------------------------------------- API-level tests (fixture data)
SCENARIOS_LEAK = ["S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT"]


@pytest.mark.parametrize("scenario_id", SCENARIOS_LEAK)
def test_no_scenario_id_title_or_expected_behavior_in_any_tool_output(trained_model, scenario_id):
    from app.agent.prompts import case_manifest
    from app.analytics.evidence import analyze_case
    from app.analytics.scenarios import SCENARIOS, apply_scenario

    bundle = services.get_repo().get(DS)
    w, r = bundle.window(2014, 120, 240), bundle.window(2014, 0, 120)
    sr = apply_scenario(w, scenario_id, 42)
    a = analyze_case("case_leak", sr.frame, r, sr, services.get_model(),
                     SampleRange(source_year=2014, start=120, end=240), SampleRange(source_year=2014, start=0, end=120))
    runner = ToolRunner(a)
    args_for = {"get_sensor_window": {"measurements": ["AFDP", "TEY", "CDP", "AT", "AH"], "start_index": 0,
                                      "end_index": 240},
                "evaluate_hypothesis": None, "lookup_reference": None}
    blobs = [case_manifest(a, "synthetic_overlay")]
    for spec in TOOL_SPECS:
        name = spec["function"]["name"]
        if name == "evaluate_hypothesis":
            for key in spec["function"]["parameters"]["properties"]["hypothesis_key"]["enum"]:
                blobs.append(json.dumps(runner.run(name, {"hypothesis_key": key})[0], default=str))
        elif name == "lookup_reference":
            for topic in spec["function"]["parameters"]["properties"]["topic"]["enum"]:
                blobs.append(json.dumps(runner.run(name, {"topic": topic})[0], default=str))
        else:
            blobs.append(json.dumps(runner.run(name, args_for.get(name) or {})[0], default=str))
    blob = "\n".join(blobs)
    info = SCENARIOS[scenario_id]
    for needle in (scenario_id, scenario_id.split("_", 1)[1], info.title, info.title[:25],
                   info.expected_behavior, info.expected_behavior[:40]):
        assert needle not in blob, needle
    assert a.data_quality.notes and not any(scenario_id in n for n in a.data_quality.notes)


def test_nan_baseline_case_persists_and_lists(client, fixture_bytes):
    df = pd.read_csv(io.BytesIO(fixture_bytes))
    df.loc[60:119, "TEY"] = np.nan  # TEY logging gap covering the whole case window
    buf = df.to_csv(index=False).encode()
    r = client.post("/api/datasets/upload", files={"file": ("tey_gap_2014.csv", buf, "text/csv")})
    assert r.status_code == 200, r.text
    ds = r.json()["dataset_id"]
    r = client.post("/api/investigations", json={"dataset_id": ds, "scenario_id": "S01_NORMAL", "use_meta": False,
                                                 **WINDOW})
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]
    got = client.get(f"/api/investigations/{case_id}")
    assert got.status_code == 200, got.text
    assert got.json()["baseline"] is None
    assert not any(e["evidence_id"].startswith("ev_tey_residual_0") for e in got.json()["evidence"])
    lst = client.get("/api/investigations")
    assert lst.status_code == 200 and any(i["case_id"] == case_id for i in lst.json())


def test_corrupt_row_is_skipped_by_list_and_500_on_get(client):
    import sqlite3

    with sqlite3.connect(str(config.DB_PATH)) as conn:
        conn.execute("INSERT OR REPLACE INTO investigations (case_id, created_at, status, scenario_id, json) "
                     "VALUES ('case_corrupt', '2099-01-01T00:00:00Z', 'completed', 'S01_NORMAL', '{\"case_id\": 1}')")
    try:
        lst = client.get("/api/investigations")
        assert lst.status_code == 200 and all(i["case_id"] != "case_corrupt" for i in lst.json())
        r = client.get("/api/investigations/case_corrupt")
        assert r.status_code == 500 and r.json()["detail"].startswith("internal data validation error")
    finally:
        with sqlite3.connect(str(config.DB_PATH)) as conn:
            conn.execute("DELETE FROM investigations WHERE case_id = 'case_corrupt'")


def test_s01_offline_on_fixture_severity_matches_flags_and_offline_reason(client):
    r = client.post("/api/investigations", json={"dataset_id": DS, "scenario_id": "S01_NORMAL", "use_meta": False,
                                                 **WINDOW})
    assert r.status_code == 200, r.text
    inv = client.get(f"/api/investigations/{r.json()['case_id']}").json()
    flagged = any({"notable_deviation", "isolated_single_sensor", "out_of_training_range"} & set(e["flags"])
                  for e in inv["evidence"])
    assert inv["report"]["severity"] == ("review" if flagged else "informational")
    fallback = [e["summary"] for e in inv["events"] if e["kind"] == "fallback"]
    assert fallback and "offline preview requested (use_meta=false)" in fallback[0]


def test_offline_reason_when_client_missing():
    out = run_investigation(make_fake_analysis(synthetic=True), LABEL, None, use_meta=True)
    assert any("Meta client not configured" in e.summary for e in out.events if e.kind == "fallback")


def _with_client_host(app, host: str):
    async def wrapper(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 50000)}
        await app(scope, receive, send)
    return wrapper


def test_train_endpoint_403_from_non_local_host(client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import models as models_api
    from app.main import app

    monkeypatch.delenv("THERMOMIND_ALLOW_REMOTE_TRAIN", raising=False)
    with TestClient(_with_client_host(app, "203.0.113.7"), raise_server_exceptions=False) as remote:
        r = remote.post("/api/models/train", json={"seed": 1})
    assert r.status_code == 403 and "localhost" in r.json()["detail"]
    assert client.post("/api/models/train", json={}).status_code == 403  # TestClient host is "testclient"
    local = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    assert models_api._train_allowed(local) and models_api._train_allowed(SimpleNamespace(
        client=SimpleNamespace(host="::1")))
    monkeypatch.setenv("THERMOMIND_ALLOW_REMOTE_TRAIN", "1")
    assert models_api._train_allowed(SimpleNamespace(client=SimpleNamespace(host="203.0.113.7")))


def test_upload_persists_and_restores_in_new_repository(client, fixture_bytes, tmp_path):
    from app.data.repository import DatasetRepository

    r = client.post("/api/datasets/upload", files={"file": ("persist_2013.csv", fixture_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    ds = r.json()["dataset_id"]
    uploads = Path(config.DATA_DIR) / "uploads"
    assert (uploads / ds / "persist_2013.csv").read_bytes() == fixture_bytes
    fresh = DatasetRepository(tmp_path / "fresh.db")
    with pytest.raises(KeyError):
        fresh.get(ds)
    assert ds in fresh.restore_uploads(uploads)
    restored = fresh.get(ds)
    assert len(restored.frame) == r.json()["rows"] and restored.years() == [2013]
    assert fresh.restore_uploads(uploads) == []  # idempotent
