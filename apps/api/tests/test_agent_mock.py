"""Agent tests with a scripted FakeMetaClient (no network)."""
from __future__ import annotations

import json

import pytest

from app.agent._fake_case import CASE_ID, SECRET, make_fake_analysis
from app.agent.meta_client import ChatResult, MetaClientError
from app.agent.orchestrator import OFFLINE_TITLE_PREFIX, run_investigation
from app.agent.report_validator import extract_json, report_hash, validate_report
from app.agent.tools import TOOL_SPECS, ToolError, ToolRunner

LABEL = "synthetic_overlay"
KNOWN = {"ev_afdp_01", "ev_tey_residual_01", "ev_cdp_01"}


def good_report(**overrides) -> dict:
    rep = {
        "case_id": CASE_ID,
        "title": "AFDP rise with TEY shortfall in 2014 samples 1200-1320",
        "summary": "AFDP rose relative to the reference while the model-derived TEY residual turned negative [ev_afdp_01][ev_tey_residual_01]. CDP stayed flat [ev_cdp_01].",
        "severity": "review",
        "scenario_label": LABEL,
        "observations": [{"statement": "AFDP median +0.70 mbar vs reference (synthetic overlay on real rows).", "evidence_ids": ["ev_afdp_01"]}],
        "hypotheses": [
            {"name": "Intake restriction", "key": "intake_restriction", "rank": 1,
             "supporting_evidence_ids": ["ev_afdp_01", "ev_tey_residual_01"], "contradicting_evidence_ids": [],
             "limitations": ["No maintenance records."], "status": "possible", "rationale": "Pattern consistent with restriction."},
            {"name": "Sensor issue", "key": "sensor_issue", "rank": 2,
             "supporting_evidence_ids": ["ev_cdp_01"], "contradicting_evidence_ids": ["ev_tey_residual_01"],
             "limitations": [], "status": "inconclusive"},
        ],
        "additional_data_needed": ["Filter maintenance log."],
        "engineer_review_checks": ["Inspect inlet filter differential pressure transmitter calibration."],
        "limitations": ["Hourly aggregates only."],
    }
    rep.update(overrides)
    return rep


def tool_call_msg(calls: list[tuple[str, dict]]) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)]}


def text_msg(content) -> dict:
    return {"role": "assistant", "content": content if isinstance(content, str) else json.dumps(content)}


STANDARD_CALLS = [("get_baseline_comparison", {}),
                  ("get_sensor_window", {"measurements": ["AFDP", "TEY", "CDP"], "start_index": 1200, "end_index": 1320}),
                  ("evaluate_hypothesis", {"hypothesis_key": "intake_restriction"}),
                  ("evaluate_hypothesis", {"hypothesis_key": "sensor_issue"}),
                  ("get_data_quality", {})]


class FakeMetaClient:
    model = "fake-muse"

    def __init__(self, scripted: list[dict], raise_on: int | None = None):
        self.scripted = list(scripted)
        self.calls: list[dict] = []
        self.raise_on = raise_on

    @property
    def configured(self) -> bool:
        return True

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "response_format": response_format})
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise MetaClientError("Meta API error 503: upstream unavailable")
        if not self.scripted:
            raise AssertionError("FakeMetaClient ran out of scripted responses")
        msg = self.scripted.pop(0)
        return ChatResult(message=msg, usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                                              "reasoning_tokens": 20},
                          latency_ms=12, model=self.model,
                          finish_reason="tool_calls" if msg.get("tool_calls") else "stop")


@pytest.fixture
def analysis():
    return make_fake_analysis(synthetic=True)


def kinds(outcome):
    return [e.kind for e in outcome.events]


# ---------------------------------------------------------------- orchestrator
def test_happy_path_calls_tools_and_accepts_report(analysis):
    client = FakeMetaClient([tool_call_msg(STANDARD_CALLS), text_msg(good_report())])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed" and out.mode == "meta_live" and out.meta_used is True
    assert out.report is not None and out.report.report_status == "draft_requires_human_review"
    assert out.report_hash == report_hash(out.report) and len(out.report_hash) == 64
    k = kinds(out)
    assert k[0] == "case_opened" and k[-1] == "report_accepted"
    assert k.count("tool_call") == 5 and k.count("tool_result") == 5 and "rewrite_requested" not in k
    tool_events = [e for e in out.events if e.kind == "tool_result"]
    assert "ev_tey_residual_01" in tool_events[0].evidence_ids  # baseline comparison returned model-derived id
    assert out.events[-1].tokens["total_tokens"] == 300
    # tool messages were fed back to the model in OpenAI format
    tool_msgs = [m for m in client.calls[1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 5 and tool_msgs[0]["tool_call_id"] == "call_0"
    assert client.calls[0]["tools"] == TOOL_SPECS
    assert out.deterministic_summary["get_baseline_comparison"]["available"] is True


def test_unknown_evidence_id_triggers_rewrite_then_accepted(analysis):
    bad = good_report(observations=[{"statement": "x", "evidence_ids": ["ev_made_up_99"]}])
    client = FakeMetaClient([tool_call_msg(STANDARD_CALLS), text_msg(bad), text_msg(good_report())])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed" and out.meta_used
    assert "rewrite_requested" in kinds(out)
    rewrite_prompt = client.calls[2]["messages"][-1]
    assert rewrite_prompt["role"] == "user" and "ev_made_up_99" in rewrite_prompt["content"]
    assert client.calls[2]["response_format"] == {"type": "json_object"}


def test_still_bad_after_rewrite_is_needs_review(analysis):
    bad = good_report(observations=[{"statement": "x", "evidence_ids": ["ev_made_up_99"]}])
    client = FakeMetaClient([tool_call_msg(STANDARD_CALLS), text_msg(bad), text_msg("not json at all")])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "needs_review" and out.report is None and out.meta_used is False
    assert out.validation_errors and "JSON" in out.validation_errors[0]
    assert kinds(out)[-1] == "fallback" and out.deterministic_summary["list_evidence"]["count"] == 3


def test_unknown_tool_name_reported_to_model_without_crash(analysis):
    calls = [("get_secret_label", {}), ("get_baseline_comparison", {})]
    client = FakeMetaClient([tool_call_msg(calls), text_msg(good_report())])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed"
    rejected = [e for e in out.events if e.kind == "tool_call" and not e.ok]
    assert len(rejected) == 1 and "unknown tool" in rejected[0].summary
    tool_msgs = [m for m in client.calls[1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_msgs[0]["content"])["error"].startswith("unknown tool")


def test_model_answering_without_tools_is_nudged(analysis):
    client = FakeMetaClient([text_msg(good_report()), tool_call_msg(STANDARD_CALLS), text_msg(good_report())])
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "completed"
    assert client.calls[1]["messages"][-1]["content"].startswith("You must call the tools")


def test_offline_preview_when_client_none(analysis):
    out = run_investigation(analysis, LABEL, None)
    assert out.status == "completed" and out.mode == "offline_preview" and out.meta_used is False
    assert out.report.title.startswith(OFFLINE_TITLE_PREFIX)
    assert [h.key for h in out.report.hypotheses][0] == "intake_restriction"
    assert [h.rank for h in out.report.hypotheses] == [1, 2, 3, 4]
    assert "fallback" in kinds(out) and out.meta_model is None


def test_offline_preview_when_use_meta_false(analysis):
    client = FakeMetaClient([])
    out = run_investigation(analysis, LABEL, client, use_meta=False)
    assert out.mode == "offline_preview" and client.calls == []


def test_client_exception_is_failed_with_safe_message(analysis):
    client = FakeMetaClient([tool_call_msg(STANDARD_CALLS)], raise_on=2)
    out = run_investigation(analysis, LABEL, client)
    assert out.status == "failed" and out.report is None
    assert out.error == "Meta API error 503: upstream unavailable"
    assert kinds(out)[-1] == "error" and out.events[-1].ok is False


# ---------------------------------------------------------------- validator
def test_unsafe_control_instruction_rejected():
    rep = good_report(engineer_review_checks=["Open the valve on the inlet bleed to compensate."])
    report, errors = validate_report(rep, CASE_ID, KNOWN, LABEL)
    assert report is None and any(e.startswith("unsafe_instruction") for e in errors)
    rep = good_report(summary="Operators should bypass the filter interlock and trip the unit.")
    assert validate_report(rep, CASE_ID, KNOWN, LABEL)[0] is None


def test_fabricated_date_rejected():
    for text in ["The deviation started on 2014-03-12.", "Observed since March 12, 2014 at the plant."]:
        report, errors = validate_report(good_report(summary=text), CASE_ID, KNOWN, LABEL)
        assert report is None and any(e.startswith("fabricated_date") for e in errors), text
    # plain year + sample reference is fine
    report, errors = validate_report(good_report(summary="Source year 2014, samples 1200-1320."), CASE_ID, KNOWN, LABEL)
    assert report is not None and errors == []


def test_case_id_and_label_mismatch_rejected():
    report, errors = validate_report(good_report(case_id="case_other"), CASE_ID, KNOWN, LABEL)
    assert report is None and any("case_id mismatch" in e for e in errors)
    report, errors = validate_report(good_report(scenario_label="real_only"), CASE_ID, KNOWN, LABEL)
    assert report is None and any("scenario_label mismatch" in e for e in errors)


def test_ranks_and_fences_and_fixed_fields():
    rep = good_report()
    rep["hypotheses"][1]["rank"] = 1
    assert validate_report(rep, CASE_ID, KNOWN, LABEL)[0] is None
    assert validate_report(good_report(hypotheses=[]), CASE_ID, KNOWN, LABEL)[0] is None
    fenced = "Here you go:\n```json\n" + json.dumps(good_report(report_status="final")) + "\n```"
    report, errors = validate_report(fenced, CASE_ID, KNOWN, LABEL)
    assert report is not None and report.report_status == "draft_requires_human_review"
    assert extract_json("prose {\"a\": 1} trailing") == {"a": 1}


# ---------------------------------------------------------------- tools
def test_get_sensor_window_bounds_enforced(analysis):
    runner = ToolRunner(analysis)
    res, ids = runner.run("get_sensor_window", {"measurements": ["AFDP", "TEY"], "start_index": 960, "end_index": 1320})
    assert res["rows"]["n"] == 360 and res["covers"] == {"reference_rows": 240, "case_window_rows": 120}
    assert res["measurements"]["AFDP"]["synthetic"] is True and res["measurements"]["TEY"]["synthetic"] is False
    assert res["measurements"]["AFDP"]["provenance_kind"] == "measured_plus_synthetic_overlay"
    assert set(ids) == {"ev_afdp_01"}
    res, _ = runner.run("get_sensor_window", {"measurements": ["AFDP"], "start_index": 1000, "end_index": 1100})
    assert res["measurements"]["AFDP"]["synthetic"] is False and res["rows"]["n"] == 100
    for args in [{"measurements": ["AFDP"], "start_index": 900, "end_index": 1000},
                 {"measurements": ["AFDP"], "start_index": 1300, "end_index": 1400},
                 {"measurements": ["AFDP"], "start_index": 1300, "end_index": 1200},
                 {"measurements": ["AFDP"], "start_index": "1200", "end_index": 1320},
                 {"measurements": ["BOGUS"], "start_index": 1200, "end_index": 1320},
                 {"measurements": [], "start_index": 1200, "end_index": 1320},
                 {"measurements": ["AFDP"], "start_index": 1200, "end_index": 1320, "extra": 1}]:
        with pytest.raises(ToolError):
            runner.run("get_sensor_window", args)
    with pytest.raises(ToolError):
        runner.run("evaluate_hypothesis", {"hypothesis_key": "root_cause"})
    with pytest.raises(ToolError):
        runner.run("lookup_reference", {"topic": "plant_manual"})


def test_tools_never_leak_expected_behavior(analysis):
    runner = ToolRunner(analysis)
    outputs = []
    for name, args in STANDARD_CALLS + [("list_evidence", {}), ("lookup_reference", {"topic": "intake_filter_fouling"})]:
        outputs.append(json.dumps(runner.run(name, args)[0]))
    blob = "\n".join(outputs)
    assert SECRET not in blob and "hidden title" not in blob and "hidden description" not in blob
    assert "expected_behavior" not in blob
    dq = json.loads(outputs[4])
    assert dq["scenario_label"] == "synthetic_overlay" and dq["synthetic_measurements"] == ["AFDP"]
    ev = json.loads(outputs[2])
    assert ev["evidence"][0]["evidence_id"] == "ev_afdp_01" and ev["evidence"][0]["observed_stat"] == 4.2


def test_tool_specs_are_openai_function_schemas():
    names = [t["function"]["name"] for t in TOOL_SPECS]
    assert names == ["get_sensor_window", "get_baseline_comparison", "evaluate_hypothesis",
                     "get_data_quality", "list_evidence", "lookup_reference"]
    for t in TOOL_SPECS:
        assert t["type"] == "function" and t["function"]["parameters"]["type"] == "object"
