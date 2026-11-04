"""Multi-turn tool loop with Muse Spark, validation, bounded rewrite, and offline preview."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app import config
from app.agent.meta_client import ChatResult, MetaClient, MetaClientError
from app.agent.prompts import SYSTEM_PROMPT, case_manifest
from app.agent.report_validator import report_hash, validate_report
from app.agent.tools import TOOL_SPECS, ToolError, ToolRunner
from app.schemas import (HYPOTHESIS_KEYS, AgentEvent, DiagnosticReport, Hypothesis,
                         InvestigationStatus, Observation)

OFFLINE_TITLE_PREFIX = "OFFLINE PREVIEW — not a Meta inference"
NUDGE = "You must call the tools before answering. Call get_baseline_comparison now."
REWRITE_PREFIX = "Your previous answer was rejected. Fix these errors and return JSON only:\n"
MAX_TOOL_RESULT_CHARS = 20000


@dataclass
class InvestigationOutcome:
    report: DiagnosticReport | None
    events: list[AgentEvent]
    status: InvestigationStatus
    meta_used: bool
    meta_model: str | None
    mode: str
    validation_errors: list[str]
    report_hash: str | None
    error: str | None
    deterministic_summary: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _Events:
    def __init__(self) -> None:
        self.items: list[AgentEvent] = []
        self.tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}

    def add(self, kind: str, summary: str, **kw: Any) -> AgentEvent:
        ev = AgentEvent(seq=len(self.items) + 1, ts_utc=_now(), kind=kind, summary=summary[:500], **kw)
        self.items.append(ev)
        return ev

    def count_tokens(self, usage: dict) -> dict[str, int]:
        step = {k: int(usage.get(k, 0) or 0) for k in self.tokens}
        for k, v in step.items():
            self.tokens[k] += v
        return step


def _summarize_result(name: str, result: dict) -> str:
    if name == "get_sensor_window":
        ms = result.get("measurements", {})
        bits = [f"{m}: median={v.get('median')}" for m, v in ms.items() if isinstance(v, dict)]
        return f"rows {result.get('rows')}: " + "; ".join(bits)
    if name == "get_baseline_comparison":
        b = result.get("baseline") or {}
        return (f"residual_mean={b.get('residual_mean')} residual_z={b.get('residual_z')}"
                if result.get("available") else "baseline not available")
    if name == "evaluate_hypothesis":
        return (f"{result.get('hypothesis_key')}: score={result.get('deterministic_support_score')} "
                f"support={len(result.get('supporting_evidence_ids', []))} "
                f"contra={len(result.get('contradicting_evidence_ids', []))}")
    if name == "get_data_quality":
        return (f"flags={len(result.get('sensor_consistency_flags', []))} "
                f"synthetic={result.get('synthetic_measurements')}")
    if name == "list_evidence":
        return f"{result.get('count')} evidence items"
    if name == "lookup_reference":
        return f"topic={result.get('topic')} ({len(result.get('notes', []))} notes)"
    return "ok"


def deterministic_summary(analysis: Any, runner: ToolRunner) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ("get_baseline_comparison", "get_data_quality", "list_evidence"):
        try:
            out[name] = runner.run(name, {})[0]
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": f"{type(exc).__name__}"}
    out["evaluate_hypothesis"] = {}
    for key in HYPOTHESIS_KEYS:
        try:
            out["evaluate_hypothesis"][key] = runner.run("evaluate_hypothesis", {"hypothesis_key": key})[0]
        except Exception as exc:  # noqa: BLE001
            out["evaluate_hypothesis"][key] = {"error": f"{type(exc).__name__}"}
    return out


def build_offline_report(analysis: Any, scenario_label: str) -> DiagnosticReport:
    evidence = list(getattr(analysis, "evidence", []) or [])
    evals = getattr(analysis, "hypothesis_evals", None) or {}
    by_id = {e.evidence_id: e for e in evidence}
    observations = []
    for e in evidence:
        prov = {"real_observation": "REAL", "model_derived": "MODEL-DERIVED",
                "synthetic_overlay": "SYNTHETIC OVERLAY",
                "measured_plus_synthetic_overlay": "REAL + SYNTHETIC OVERLAY"}.get(e.kind, e.kind)
        stmt = f"[{prov}] {e.title}: {e.computation}"
        if e.z_score is not None:
            stmt += f" (z={e.z_score:.2f})"
        observations.append(Observation(statement=stmt, evidence_ids=[e.evidence_id]))
    ordered = sorted(evals.values(), key=lambda h: -float(h.deterministic_support_score))
    hypotheses = []
    for rank, h in enumerate(ordered, start=1):
        score = float(h.deterministic_support_score)
        status = "possible" if score >= 0.5 else ("inconclusive" if score >= 0.2 else "not_supported")
        hypotheses.append(Hypothesis(
            name=h.hypothesis_key.replace("_", " ").capitalize(), key=h.hypothesis_key, rank=rank,
            supporting_evidence_ids=[i for i in h.supporting_evidence_ids if i in by_id],
            contradicting_evidence_ids=[i for i in h.contradicting_evidence_ids if i in by_id],
            limitations=["Deterministic heuristic score only; no model reasoning was applied."],
            status=status,
            rationale=f"deterministic_support_score={score:.2f} (heuristic). " + " ".join(h.deterministic_notes),
            what_would_change_assessment="A Meta-model investigation with tool access, or additional plant data.",
        ))
    if not hypotheses:
        hypotheses.append(Hypothesis(name="Unknown", key="unknown", rank=1, status="inconclusive",
                                     rationale="No deterministic hypothesis evaluations were available.",
                                     limitations=["No hypothesis evaluations available."]))
    max_z = max([abs(e.z_score) for e in evidence if e.z_score is not None] or [0.0])
    severity = "review" if max_z >= 3.0 else "informational"
    return DiagnosticReport(
        case_id=analysis.case_id,
        title=f"{OFFLINE_TITLE_PREFIX}: deterministic summary for {analysis.case_id}",
        summary=(f"Offline preview assembled from deterministic tool outputs only; no Meta model was called. "
                 f"{len(evidence)} evidence items, {len(hypotheses)} hypotheses ranked by heuristic score. "
                 f"Scenario label: {scenario_label}. Human review required."),
        severity=severity,
        scenario_label=scenario_label,
        observations=observations,
        hypotheses=hypotheses,
        additional_data_needed=["Run a live Meta investigation for reasoned hypothesis ranking.",
                                "Maintenance and calibration records (not present in the UCI dataset)."],
        engineer_review_checks=["Review each evidence item's provenance (real / model-derived / synthetic).",
                                "Cross-check deviating measurements against physically coupled channels."],
        limitations=["Deterministic preview; heuristic scores are not probabilities.",
                     "UCI data has no timestamps and no verified fault labels."],
    )


def _parse_tool_args(raw: Any) -> dict:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        obj = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ToolError(f"tool arguments are not valid JSON: {exc.msg if hasattr(exc, 'msg') else exc}")
    if not isinstance(obj, dict):
        raise ToolError("tool arguments must be a JSON object")
    return obj


def _tool_message(call_id: str, payload: dict) -> dict:
    content = json.dumps(payload, default=str)
    if len(content) > MAX_TOOL_RESULT_CHARS:
        content = content[:MAX_TOOL_RESULT_CHARS] + '..."truncated":true}'
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def run_investigation(analysis: Any, scenario_label: str, client: MetaClient | None,
                      use_meta: bool = True) -> InvestigationOutcome:
    events = _Events()
    runner = ToolRunner(analysis)
    events.add("case_opened", f"case {analysis.case_id} opened ({scenario_label}); "
                              f"{len(runner.known_evidence_ids)} evidence items")
    summary = deterministic_summary(analysis, runner)

    live = client is not None and getattr(client, "configured", False) and use_meta
    if not live:
        reason = "use_meta=False" if client is not None and getattr(client, "configured", False) \
            else "Meta client not configured"
        events.add("fallback", f"offline preview ({reason}); no Meta inference performed")
        report = build_offline_report(analysis, scenario_label)
        report, errors = validate_report(report.model_dump(), analysis.case_id,
                                         runner.known_evidence_ids, scenario_label)
        if report is not None:
            events.add("report_accepted", "offline preview report built deterministically",
                       tokens=dict(events.tokens))
            return InvestigationOutcome(report=report, events=events.items, status="completed",
                                        meta_used=False, meta_model=None, mode="offline_preview",
                                        validation_errors=[], report_hash=report_hash(report),
                                        error=None, deterministic_summary=summary)
        events.add("validation", "offline preview failed validation", ok=False, tokens=dict(events.tokens))
        return InvestigationOutcome(report=None, events=events.items, status="needs_review",
                                    meta_used=False, meta_model=None, mode="offline_preview",
                                    validation_errors=errors, report_hash=None, error=None,
                                    deterministic_summary=summary)

    model_name = getattr(client, "model", None) or config.META_MODEL
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": case_manifest(analysis, scenario_label)}]
    max_rounds = max(1, int(config.META_MAX_TOOL_ROUNDS))
    tools_called = 0
    nudged = False
    last: ChatResult | None = None

    def chat(tools: list[dict] | None, label: str, response_format: dict | None = None) -> ChatResult:
        events.add("model_request", f"{label}: {len(messages)} messages -> {model_name}")
        res = client.chat(messages, tools, config.META_MAX_TOKENS, response_format=response_format)
        step = events.count_tokens(res.usage or {})
        n_calls = len(res.message.get("tool_calls") or [])
        events.add("model_response", f"finish={res.finish_reason}; tool_calls={n_calls}; "
                                     f"content_chars={len(res.message.get('content') or '')}",
                   latency_ms=res.latency_ms, tokens=step)
        messages.append(res.message)
        return res

    try:
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            last = chat(TOOL_SPECS, f"round {rounds}/{max_rounds}")
            tool_calls = last.message.get("tool_calls") or []
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or "?"
                    call_id = tc.get("id") or f"call_{events.items[-1].seq}"
                    try:
                        args = _parse_tool_args(fn.get("arguments"))
                        result, ids = runner.run(name, args)
                    except ToolError as exc:
                        events.add("tool_call", f"{name}: rejected ({exc})", tool_name=name, ok=False)
                        messages.append(_tool_message(call_id, {"error": str(exc)}))
                        continue
                    tools_called += 1
                    events.add("tool_call", f"{name}({json.dumps(args, default=str)[:200]})",
                               tool_name=name, args=args)
                    events.add("tool_result", _summarize_result(name, result), tool_name=name,
                               evidence_ids=list(ids))
                    messages.append(_tool_message(call_id, result))
                continue
            if tools_called == 0 and not nudged:
                nudged = True
                events.add("rewrite_requested", "model answered without calling tools; nudged once")
                messages.append({"role": "user", "content": NUDGE})
                continue
            break

        def final_content(res: ChatResult | None) -> str:
            if res is None:
                return ""
            if res.finish_reason == "length" and not res.message.get("content"):
                return ""
            return res.message.get("content") or ""

        content = final_content(last)
        if tools_called == 0:
            report, errors = None, ["model produced no tool calls; a report without tool evidence is not accepted"]
        else:
            report, errors = validate_report(content, analysis.case_id, runner.known_evidence_ids, scenario_label)
            if last is not None and last.finish_reason == "length" and not last.message.get("content"):
                errors = ["model response truncated (finish_reason=length); return the JSON report only"] + errors
            if last is not None and last.message.get("tool_calls") and not content:
                errors = ["tool round limit reached while still calling tools; return the JSON report now"] + errors
        events.add("validation", "report accepted" if report else f"{len(errors)} validation error(s)",
                   ok=report is not None)

        if report is None and tools_called > 0:
            events.add("rewrite_requested", "one rewrite turn; errors: " + " | ".join(errors)[:400])
            messages.append({"role": "user", "content": REWRITE_PREFIX + "\n".join(f"- {e}" for e in errors)})
            last = chat(None, "rewrite", response_format={"type": "json_object"})
            content = final_content(last)
            report, errors = validate_report(content, analysis.case_id, runner.known_evidence_ids, scenario_label)
            events.add("validation", "rewrite accepted" if report else f"rewrite still has {len(errors)} error(s)",
                       ok=report is not None)

        if report is not None:
            events.add("report_accepted", f"Meta report accepted; {tools_called} tool calls; "
                                          f"{len(report.hypotheses)} hypotheses", tokens=dict(events.tokens))
            return InvestigationOutcome(report=report, events=events.items, status="completed",
                                        meta_used=True, meta_model=last.model if last else model_name,
                                        mode="meta_live", validation_errors=[],
                                        report_hash=report_hash(report), error=None,
                                        deterministic_summary=summary)
        events.add("fallback", "report rejected after rewrite; deterministic summary available for review",
                   ok=False, tokens=dict(events.tokens))
        return InvestigationOutcome(report=None, events=events.items, status="needs_review",
                                    meta_used=False, meta_model=last.model if last else model_name,
                                    mode="meta_live", validation_errors=errors, report_hash=None,
                                    error=None, deterministic_summary=summary)
    except MetaClientError as exc:
        msg = str(exc)
    except Exception as exc:  # noqa: BLE001 - never leak raw provider errors
        msg = f"unexpected error during investigation ({type(exc).__name__})"
    events.add("error", msg, ok=False, tokens=dict(events.tokens))
    return InvestigationOutcome(report=None, events=events.items, status="failed", meta_used=False,
                                meta_model=model_name, mode="meta_live", validation_errors=[],
                                report_hash=None, error=msg, deterministic_summary=summary)
