"""Tests for app.features.ops (handover draft, CMMS draft export, prototype metrics). No network."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.meta_client import ChatResult, MetaClientError
from app.features.ops import handover, router as ops_router
from app.features.ops.cmms import build_work_order, safe_cell, work_order_csv
from app.features.ops.metrics import compute_metrics
from app.features.ops.schemas import CMMS_STATUS, OFFLINE_LABEL, HandoverDraft
from app.schemas import (AgentEvent, DiagnosticReport, Evidence, Hypothesis, Investigation, InvestigationRequest,
                         Observation, ReviewRecord, SampleRange, ScenarioInfo)

NOW = datetime(2026, 11, 4, 20, 0, 0, tzinfo=timezone.utc)
WIN = SampleRange(source_year=2014, start=1200, end=1320)
REF = SampleRange(source_year=2014, start=960, end=1200)


def _ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_inv(case_id: str, *, synthetic: bool, live: bool, minutes_ago: float = 30, review: str | None = None,
             severity: str = "review", title: str = "AFDP rise with TEY shortfall", checks: list[str] | None = None,
             first_pass_ok: bool = True) -> Investigation:
    scen = ScenarioInfo(
        scenario_id="S02_INTAKE_RESTRICTION" if synthetic else "S01_NORMAL",
        title="Intake restriction (synthetic)" if synthetic else "Normal operation (real)", synthetic=synthetic,
        description="d", rationale="r", affected_measurements=["AFDP"] if synthetic else [], expected_behavior="x")
    label = "synthetic_overlay" if synthetic else "real_only"
    evidence = [
        Evidence(evidence_id=f"ev_{m}_01", case_id=case_id, kind="real_observation", metric=m.upper(), unit="mbar",
                 title=m, sample_range=WIN, reference_range=REF, observed_stat=1.0, comparison_stat=1.0,
                 method="median_window_vs_reference", computation="c")
        for m in ("afdp", "cdp", "tey")
    ]
    report = DiagnosticReport(
        case_id=case_id, title=title, summary="Window shows AFDP above reference.", severity=severity,
        scenario_label=label,
        observations=[Observation(statement="AFDP up", evidence_ids=["ev_afdp_01"])],
        hypotheses=[Hypothesis(name="Intake restriction", key="intake_restriction", rank=1, status="possible",
                               supporting_evidence_ids=["ev_afdp_01", "ev_tey_01"],
                               contradicting_evidence_ids=["ev_cdp_01"]),
                    Hypothesis(name="Sensor issue", key="sensor_issue", rank=2, status="inconclusive")],
        additional_data_needed=[], engineer_review_checks=checks or ["Inspect filter house dP trend"],
        limitations=[])
    t0 = minutes_ago
    events = [AgentEvent(seq=1, ts_utc=_ts(t0), kind="case_opened", summary="opened")]
    if live:
        events += [
            AgentEvent(seq=2, ts_utc=_ts(t0 - 0.0), kind="model_request", summary="r1"),
            AgentEvent(seq=3, ts_utc=_ts(t0 - 0.5), kind="tool_call", tool_name="list_evidence", summary="t"),
            AgentEvent(seq=4, ts_utc=_ts(t0 - 0.5), kind="tool_call", tool_name="bad", summary="t", ok=False),
            AgentEvent(seq=5, ts_utc=_ts(t0 - 0.6), kind="tool_call", tool_name="get_data_quality", summary="t"),
            AgentEvent(seq=6, ts_utc=_ts(t0 - 1.0), kind="validation", summary="v", ok=first_pass_ok),
        ]
        if not first_pass_ok:
            events += [AgentEvent(seq=7, ts_utc=_ts(t0 - 1.1), kind="rewrite_requested", summary="one rewrite turn"),
                       AgentEvent(seq=8, ts_utc=_ts(t0 - 1.5), kind="validation", summary="ok")]
        events.append(AgentEvent(seq=len(events) + 1, ts_utc=_ts(t0 - 2.0), kind="report_accepted", summary="a"))
    else:
        events += [AgentEvent(seq=2, ts_utc=_ts(t0), kind="fallback", summary="offline"),
                   AgentEvent(seq=3, ts_utc=_ts(t0), kind="report_accepted", summary="a")]
    rev = ReviewRecord(decision=review, reviewer="demo-engineer", ts_utc=_ts(minutes_ago - 10)) if review else None
    return Investigation(
        case_id=case_id, status="completed", created_at_utc=_ts(minutes_ago), completed_at_utc=_ts(minutes_ago - 2),
        request=InvestigationRequest(dataset_id="ds_uci_551", scenario_id=scen.scenario_id), scenario=scen,
        scenario_label=label, window=WIN, reference=REF, model_version="baseline_v1",
        meta_model="muse-spark-1.3" if live else None, meta_used=live, mode="meta_live" if live else "offline_preview",
        report=report, evidence=evidence, events=events, review=rev, report_hash="h" * 64)


@pytest.fixture
def invs() -> list[Investigation]:
    return [make_inv("case_aaa111", synthetic=False, live=True, minutes_ago=30, review="accepted"),
            make_inv("case_bbb222", synthetic=True, live=False, minutes_ago=60, severity="urgent_review"),
            make_inv("case_old999", synthetic=True, live=False, minutes_ago=60 * 30)]  # outside any window


class FakeMetaClient:
    configured = True
    model = "muse-spark-1.3"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "max_tokens": max_tokens,
                           "response_format": response_format})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        content = r if isinstance(r, str) else json.dumps(r)
        return ChatResult(message={"role": "assistant", "content": content}, usage={"total_tokens": 100},
                          latency_ms=7, model=self.model, finish_reason="stop")


def good_draft(**over) -> dict:
    d = {"headline": "DRAFT: 2 cases this shift; case_bbb222 (SYNTHETIC OVERLAY) awaits review.",
         "open_items": [{"case_id": "case_bbb222", "text": "SYNTHETIC OVERLAY intake scenario awaiting review."}],
         "watch_list": [{"case_id": None, "text": "Meta configured; data ready."}],
         "completed": [{"case_id": "case_aaa111", "text": "REAL DATA case accepted by demo-engineer."}],
         "caveats": ["DRAFT — requires shift supervisor sign-off"]}
    d.update(over)
    return d


@pytest.fixture
def store(tmp_path):
    return handover.HandoverStore(tmp_path / "ops.db")


def _gen(client, invs, store, **kw):
    return handover.generate_handover(hours=kw.pop("hours", 8), persona="shift_supervisor", investigations=invs,
                                      client=client, store=store, health={"meta_configured": True, "blockers": []},
                                      now=NOW, **kw)


# ----------------------------------------------------------------------------- handover
def test_handover_valid_json_accepted_and_persisted(invs, store):
    fake = FakeMetaClient([good_draft()])
    note = _gen(fake, invs, store)
    assert note.mode == "meta_live" and note.meta_used and note.meta_calls == 1 and not note.rewrite_used
    assert len(fake.calls) == 1 and fake.calls[0]["max_tokens"] == 3000
    assert fake.calls[0]["messages"][0]["content"].startswith("Draft a shift handover note")
    assert {c.case_id for c in note.cases} == {"case_aaa111", "case_bbb222"}  # case_old999 outside 8 h
    assert note.status.startswith("DRAFT") and len(note.note_hash) == 64
    assert store.get(note.note_id).note_hash == note.note_hash
    assert [n.note_id for n in store.list()] == [note.note_id]
    payload = fake.calls[0]["messages"][1]["content"]
    assert "case_old999" not in payload and "SYNTHETIC OVERLAY" in payload and "REAL DATA" in payload


def test_handover_window_24h_still_excludes_older_cases(invs, store):
    note = _gen(FakeMetaClient([good_draft()]), invs, store, hours=24)
    assert "case_old999" not in {c.case_id for c in note.cases}


def test_unknown_case_id_rejected_then_rewrite_accepted(invs, store):
    bad = good_draft(open_items=[{"case_id": "case_zzz000", "text": "invented case"}])
    fake = FakeMetaClient([bad, good_draft()])
    note = _gen(fake, invs, store)
    assert note.meta_used and note.rewrite_used and note.meta_calls == 2
    assert any("unknown case ids" in e for e in note.validation_errors)
    assert "case_zzz000" in fake.calls[1]["messages"][-1]["content"]


def test_unknown_case_id_rewrite_fails_then_fallback(invs, store):
    bad = good_draft(open_items=[{"case_id": "case_zzz000", "text": "invented"}])
    bad_text = good_draft(headline="See case_qqq777 too.")
    fake = FakeMetaClient([bad, bad_text])
    note = _gen(fake, invs, store)
    assert note.mode == "offline_fallback" and not note.meta_used and note.meta_calls == 2
    assert note.fallback_reason == "Meta draft rejected after one bounded rewrite"
    assert "rejected" in note.source_label
    assert {i.case_id for i in note.draft.open_items} <= {"case_aaa111", "case_bbb222"}


def test_unsafe_phrase_rejected(invs, store):
    unsafe = good_draft(watch_list=[{"case_id": "case_bbb222", "text": "Operator should close the bleed valve."}])
    draft, errs = handover.validate_draft(unsafe, {"case_aaa111", "case_bbb222"})
    assert draft is None and any("unsafe_instruction" in e for e in errs)
    dated = good_draft(headline="Event on 2014-03-02 at the plant")
    assert handover.validate_draft(dated, {"case_aaa111", "case_bbb222"})[0] is None
    fake = FakeMetaClient([unsafe, good_draft(caveats=[])])
    note = _gen(fake, invs, store)
    assert note.meta_used and note.rewrite_used
    assert any("DRAFT" in c for c in note.draft.caveats)  # server adds the DRAFT caveat when missing


def test_offline_fallback_when_client_none(invs, store):
    note = _gen(None, invs, store)
    assert note.mode == "offline_fallback" and note.meta_calls == 0 and note.source_label == OFFLINE_LABEL
    assert note.fallback_reason == "Meta client not configured"
    texts = " ".join(i.text for i in note.draft.open_items)
    assert "SYNTHETIC OVERLAY" in texts and "case_bbb222" == note.draft.open_items[0].case_id
    assert [c.case_id for c in note.draft.completed] == ["case_aaa111"]
    assert HandoverDraft.model_validate(note.draft.model_dump())


def test_meta_error_falls_back(invs, store):
    note = _gen(FakeMetaClient([MetaClientError("Meta API rate limited (429)")]), invs, store)
    assert note.mode == "offline_fallback" and "429" in (note.fallback_reason or "")


def test_handover_includes_open_work_requests(invs, store):
    wr = {"id": "wr_1", "case_id": "case_old999", "assigned_persona": "ic_engineer", "status": "open",
          "title": "Check CDP transmitter"}
    done = {"id": "wr_2", "case_id": "case_aaa111", "assigned_persona": "x", "status": "done", "title": "t"}
    ghost = {"id": "wr_3", "case_id": "case_nope", "assigned_persona": "x", "status": "open", "title": "t"}
    note = _gen(None, invs, store, work_requests=[wr, done, ghost], work_requests_available=True)
    assert note.work_requests_included == 1
    assert "case_old999" in {c.case_id for c in note.cases}  # referenced by an open WR -> in scope
    assert any("wr_1" in i.text for i in note.draft.open_items)


# ----------------------------------------------------------------------------- CMMS
def test_cmms_json_shape(invs):
    doc = build_work_order(invs[1], "shift_supervisor", generated_at="2026-11-04T20:00:00Z")
    wo = doc["work_order_draft"]
    assert wo["external_ref"] == "case_bbb222" and wo["priority"] == "P1"
    assert wo["asset"] == "GT-1 (UCI dataset 551, undisclosed Turkish plant)"
    assert wo["status"] == CMMS_STATUS and wo["system"] == "ThermoMind prototype — no CMMS integration"
    assert wo["requested_by"] == "shift_supervisor" and wo["title"].startswith("[SYNTHETIC OVERLAY]")
    assert "ev_afdp_01" in wo["description"] and "Intake restriction" in wo["description"]
    assert wo["tasks"] == [{"seq": 1, "text": "Inspect filter house dP trend", "type": "engineer_review_check"}]
    assert doc["provenance"]["synthetic"] is True


def test_cmms_csv_injection_safe():
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and safe_cell("+1") == "'+1"
    assert safe_cell("-2") == "'-2" and safe_cell("@SUM(A1)") == "'@SUM(A1)" and safe_cell("ok") == "ok"
    inv = make_inv("case_ccc333", synthetic=False, live=False, title="=cmd|' /C calc'!A0",
                   checks=["=1+1", "@SUM(A1:A2)", "-negative", "+plus", "normal check"])
    text = work_order_csv(build_work_order(inv, "@attacker"))
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    assert header[0] == "external_ref" and len(body) == 5
    for row in body:
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@")), cell
    col = header.index("task_text")
    assert [r[col] for r in body] == ["'=1+1", "'@SUM(A1:A2)", "'-negative", "'+plus", "normal check"]
    assert body[0][header.index("requested_by")] == "'@attacker"


# ----------------------------------------------------------------------------- metrics
def test_metrics_empty_store():
    m = compute_metrics([])
    assert m.cases_total == 0 and m.live_cases == 0 and m.live_wall_time_s.median is None
    assert m.validator_first_pass_acceptance.rate is None and m.cited_ids_resolving.n == 0
    assert m.notice == "prototype metrics from this demo database, not pilot results"


def test_metrics_two_cases():
    a = make_inv("case_aaa111", synthetic=False, live=True, minutes_ago=30, review="accepted", first_pass_ok=False)
    b = make_inv("case_bbb222", synthetic=True, live=False, minutes_ago=60)
    m = compute_metrics([a, b])
    assert m.cases_total == 2 and m.by_mode == {"meta_live": 1, "offline_preview": 1}
    assert m.by_scenario_label == {"real_only": 1, "synthetic_overlay": 1}
    assert m.live_wall_time_s.median == 120.0 and m.live_wall_time_s.n == 1
    assert m.tool_calls_per_live_case.median == 2.0  # failed tool call excluded
    assert m.validator_first_pass_acceptance.rate == 0.0 and m.rewrite_rate.rate == 1.0
    assert m.review_counts["accepted"] == 1 and m.review_counts["unreviewed"] == 1
    assert m.evidence_citations_per_report.median == 3.0
    assert m.cited_ids_resolving.rate == 1.0 and m.cited_ids_resolving.n == 6
    assert m.time_to_review_s.median == 600.0


# ----------------------------------------------------------------------------- HTTP
@pytest.fixture
def client(invs, store, monkeypatch):
    by_id = {i.case_id: i for i in invs}

    def get_inv(cid):
        return by_id[cid]

    monkeypatch.setattr(ops_router, "get_investigations", lambda: list(invs))
    monkeypatch.setattr(ops_router, "get_investigation", get_inv)
    monkeypatch.setattr(ops_router, "get_meta_client", lambda: None)
    monkeypatch.setattr(ops_router, "get_work_requests", lambda: ([], False))
    monkeypatch.setattr(ops_router, "get_health_flags", lambda: {"meta_configured": False, "blockers": []})
    monkeypatch.setattr(ops_router, "get_handover_store", lambda: store)
    app = FastAPI()
    app.include_router(ops_router.router, prefix="/api")
    return TestClient(app)


def test_http_routes_and_404s(client):
    r = client.get("/api/ops/cmms/case_bbb222.json")
    assert r.status_code == 200 and r.json()["work_order_draft"]["external_ref"] == "case_bbb222"
    assert "attachment" in r.headers["content-disposition"]
    r = client.get("/api/ops/cmms/case_bbb222.csv", headers={"X-Persona": "ic_engineer"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "ic_engineer" in r.text
    assert client.get("/api/ops/cmms/case_nope.json").status_code == 404
    assert client.get("/api/ops/cmms/case_nope.csv").status_code == 404
    assert client.get("/api/ops/handover/ho_missing").status_code == 404
    assert client.post("/api/ops/handover", json={"hours": 6}).status_code == 422
    r = client.post("/api/ops/handover", json={"hours": 24, "persona": "shift_supervisor"})
    assert r.status_code == 200 and r.json()["source_label"] == OFFLINE_LABEL
    nid = r.json()["note_id"]
    assert client.get(f"/api/ops/handover/{nid}").json()["note_hash"] == r.json()["note_hash"]
    assert [n["note_id"] for n in client.get("/api/ops/handover").json()] == [nid]
    m = client.get("/api/ops/metrics").json()
    assert m["cases_total"] == 3 and "not pilot results" in m["notice"]
