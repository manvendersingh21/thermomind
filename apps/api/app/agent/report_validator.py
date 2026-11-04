"""Validate a model-produced DiagnosticReport before it is accepted."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from app.schemas import UCI_SOURCE_ID, DiagnosticReport

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")

# Phrases that turn an otherwise legitimate verb into a description rather than an instruction
# ("ambient temperature would reduce output", "a decrease in load"). Fixed-width lookbehinds keep
# UNSAFE_PATTERNS a plain list of (label, compiled pattern) for the other scanners that import it.
_NOT_DESCRIPTIVE = "".join(
    f"(?<!{w} )" for w in ("would", "could", "might", "may", "can", "will", "tends to", "tend to",
                           "likely to", "expected to", "does not", "did not", "\\ba", "\\ban", "the",
                           "any", "\\bno", "this")
)
# optional article + up to two filler words that are not prepositions/conjunctions (stays inside one clause)
_FILL = (r"(?:\s+(?:the|a|an|its|all|any|this|that)\b)?"
         r"(?:\s+(?!(?:in|on|at|across|of|for|from|to|with|during|while|when|by|and|or|as|over|than|under|"
         r"between|ambient|if|whether|about)\b)[\w-]+){0,2}?")
_CHANGE_VERBS = r"(reduce|lower|raise|increase|decrease|cut|ramp|de-?rate|curtail|boost)"
_CHANGE_TARGETS = r"(load|output|firing|tit|temperatures?|speed|unit|power|generation)"
_OP_VERBS = (r"(stop|start|restart|isolate|reset|close|open|trip|shut\s+off|switch\s+(?:on|off)|"
             r"turn\s+(?:on|off)|de-?energi[sz]e)")
_OP_TARGETS = (r"(turbines?|units?|gts?|fuel|igvs?|relays?|breakers?|valves?|pumps?|compressors?|"
               r"generators?|dampers?|machines?|plant)")
_EQUIPMENT = r"(unit|turbine|machine|gt|plant|generator|compressor)"

UNSAFE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (label, re.compile(pat, re.IGNORECASE)) for label, pat in [
        ("open the valve", r"\bopen(ing)?\s+(the\s+)?\w*\s*valve"),
        ("close the valve", r"\bclos(e|ing)\s+(the\s+)?\w*\s*valve"),
        ("set the setpoint", r"\bset(ting)?\s+(the\s+)?\w*\s*set-?point"),
        ("change the setpoint", r"\b(chang|adjust|rais|lower|increas|decreas)(e|ing)\s+(the\s+)?\w*\s*set-?point"),
        ("trip", r"\btrip(s|ped|ping)?\s+(the\s+)?(unit|turbine|machine|gt|generator)\b|\binitiate\s+a\s+trip\b"
                 rf"|{_NOT_DESCRIPTIVE}\btrip(ping)?\s+the\b"),
        ("shutdown the unit",
         rf"{_NOT_DESCRIPTIVE}\bshut(ting)?\s*-?\s*down\s+(the\s+|a\s+)?(\w+\s+)?{_EQUIPMENT}\b"
         rf"|\bshut\s+(the\s+)?(\w+\s+)?{_EQUIPMENT}\s+down\b"
         r"|\b(initiate|perform|execute|order|begin|carry\s+out|request)\s+(an?\s+|the\s+)?(\w+\s+)?"
         r"(shutdown|shut-down|trip)\b"),
        ("change load/output/firing", rf"{_NOT_DESCRIPTIVE}\b{_CHANGE_VERBS}(?:\s+(?:up|down|back))?{_FILL}"
                                      rf"\s+{_CHANGE_TARGETS}\b"
                                      r"(?!\s+(?:periods?|conditions?|regimes?|samples?|rows?|cases?|windows?|levels?\s+in))"),
        ("operate equipment", rf"{_NOT_DESCRIPTIVE}\b{_OP_VERBS}(?:\s+(?:up|down|off))?{_FILL}\s+{_OP_TARGETS}\b"),
        ("override interlock",
         rf"{_NOT_DESCRIPTIVE}\b(bypass(ing)?|defeat(ing)?|disabl(e|ing)|forc(e|ing)|inhibit(ing)?|overrid(e|ing)|"
         rf"jumper(ing)?){_FILL}\s+(interlocks?|protections?|alarms?|safet(y|ies)|permissives?)\b"),
        ("adjust fuel", r"\b(adjust|increase|decrease|reduce|raise|lower|cut)\w*\s+(the\s+)?fuel\b"),
        ("command", r"\b(issue|send|execute|dispatch)\b[^.]{0,30}\bcommand(s)?\b|\bcommand(s|ed|ing)?\b[^.]{0,40}\b(valve|breaker|setpoint|turbine|fuel|plc|dcs|scada|governor)\b"),
    ]
]

_MONTHS = (r"(January|February|March|April|May|June|July|August|September|October|November|December|"
           r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)")
DATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(19|20)\d\d[-/.]\d{1,2}[-/.]\d{1,2}\b"),           # 2014-03-05, 2014-3-5, 2014/03/05
    re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.](19|20)\d\d\b"),           # 05.03.2014, 5/3/2014, 05-03-2014
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(st|nd|rd|th)?(,?\s+20\d\d)?\b"),
    re.compile(rf"\b\d{{1,2}}(st|nd|rd|th)?\s+(of\s+)?{_MONTHS}\.?(,?\s+20\d\d)?\b"),
    re.compile(rf"\b{_MONTHS}\.?,?\s+(of\s+)?(19|20)\d\d\b"),           # March 2014
    re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?\b"),           # 14:00, 9:30:15
    re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b"),
]
INLINE_EVIDENCE_ID = re.compile(r"\bev_[a-z0-9_]+\b")


def extract_json(raw: str) -> dict | None:
    """Parse the first JSON object from text; strips ``` fences and surrounding prose."""
    if raw is None:
        return None
    text = _FENCE.sub("", str(raw).strip())
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    decoder = json.JSONDecoder()
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = text.find("{", start + 1)
    return None


def _texts(report: DiagnosticReport) -> list[tuple[str, str]]:
    out = [("title", report.title), ("summary", report.summary), ("data_source", report.data_source)]
    for i, o in enumerate(report.observations):
        out.append((f"observations[{i}].statement", o.statement))
    for i, h in enumerate(report.hypotheses):
        out.append((f"hypotheses[{i}].name", h.name))
        if h.key:
            out.append((f"hypotheses[{i}].key", h.key))
        if h.rationale:
            out.append((f"hypotheses[{i}].rationale", h.rationale))
        if h.what_would_change_assessment:
            out.append((f"hypotheses[{i}].what_would_change_assessment", h.what_would_change_assessment))
        for j, lim in enumerate(h.limitations):
            out.append((f"hypotheses[{i}].limitations[{j}]", lim))
    for field in ("additional_data_needed", "engineer_review_checks", "limitations"):
        for j, s in enumerate(getattr(report, field)):
            out.append((f"{field}[{j}]", s))
    return out


def validate_report(raw: dict | str, case_id: str, known_evidence_ids: set[str],
                    scenario_label: str) -> tuple[DiagnosticReport | None, list[str]]:
    errors: list[str] = []
    if isinstance(raw, dict):
        data = raw
    else:
        data = extract_json(raw) if raw else None
        if data is None:
            return None, ["response is not a JSON object (expected a DiagnosticReport JSON object, no prose)"]
    # Fixed fields are not the model's to choose; normalise before pydantic.
    data = dict(data)
    data["report_status"] = "draft_requires_human_review"
    data["disclaimer"] = "Not a validated plant safety or control system."
    data["data_source"] = UCI_SOURCE_ID
    try:
        report = DiagnosticReport.model_validate(data)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", ()))
            errors.append(f"schema: {loc}: {e.get('msg')}")
        return None, errors

    if report.case_id != case_id:
        errors.append(f"case_id mismatch: got '{report.case_id}', expected '{case_id}'")
    if report.scenario_label != scenario_label:
        errors.append(f"scenario_label mismatch: got '{report.scenario_label}', expected '{scenario_label}'")

    cited: list[tuple[str, str]] = []
    for i, o in enumerate(report.observations):
        cited += [(f"observations[{i}]", e) for e in o.evidence_ids]
    for i, h in enumerate(report.hypotheses):
        cited += [(f"hypotheses[{i}].supporting", e) for e in h.supporting_evidence_ids]
        cited += [(f"hypotheses[{i}].contradicting", e) for e in h.contradicting_evidence_ids]
    unknown = sorted({e for _, e in cited if e not in known_evidence_ids})
    if unknown:
        errors.append(f"unknown evidence_ids cited: {unknown}; allowed: {sorted(known_evidence_ids)}")

    if not report.hypotheses:
        errors.append("at least one hypothesis is required")
    else:
        ranks = sorted(h.rank for h in report.hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            errors.append(f"hypothesis ranks must be unique 1..{len(ranks)}; got {ranks}")

    inline_unknown: list[str] = []
    for where, text in _texts(report):
        for m in INLINE_EVIDENCE_ID.finditer(text or ""):
            if m.group(0) not in known_evidence_ids and m.group(0) not in inline_unknown:
                inline_unknown.append(m.group(0))
                errors.append(f"unknown evidence_id '{m.group(0)}' mentioned inline in {where}; cite only ids "
                              f"returned by tools in this conversation")
        for label, pat in UNSAFE_PATTERNS:
            if pat.search(text or ""):
                errors.append(f"unsafe_instruction: '{label}' pattern found in {where}: "
                              f"control actions are forbidden; rephrase as an engineer check or remove")
                break
        for pat in DATE_PATTERNS:
            m = pat.search(text or "")
            if m:
                errors.append(f"fabricated_date: '{m.group(0)}' in {where}: the data has no timestamps; "
                              f"refer to source_year + sample row index only")
                break
    return (report if not errors else None), errors


def report_hash(report: DiagnosticReport) -> str:
    canonical = json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
