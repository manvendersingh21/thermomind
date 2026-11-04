"""Validate a model-produced DiagnosticReport before it is accepted."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from app.schemas import DiagnosticReport

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")

UNSAFE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (label, re.compile(pat, re.IGNORECASE)) for label, pat in [
        ("open the valve", r"\bopen(ing)?\s+(the\s+)?\w*\s*valve"),
        ("close the valve", r"\bclos(e|ing)\s+(the\s+)?\w*\s*valve"),
        ("set the setpoint", r"\bset(ting)?\s+(the\s+)?\w*\s*set-?point"),
        ("change the setpoint", r"\b(chang|adjust|rais|lower|increas|decreas)(e|ing)\s+(the\s+)?\w*\s*set-?point"),
        ("trip", r"\btrip(s|ped|ping)?\s+(the\s+)?(unit|turbine|machine|gt|generator)\b|\binitiate\s+a\s+trip\b"),
        ("shutdown the unit", r"\bshut\s*-?\s*down\s+(the\s+)?(unit|turbine|machine|gt|plant)\b|\bshutdown\b"),
        ("bypass", r"\bbypass(ing|ed)?\b"),
        ("override interlock", r"\boverrid(e|ing)\b|\b(bypass\w*|defeat\w*|disabl\w*|forc\w*)\s+(the\s+)?\w*\s*interlock"),
        ("adjust fuel", r"\b(adjust|increase|decrease|reduce|raise|lower|cut)\w*\s+(the\s+)?fuel\b"),
        ("command", r"\b(issue|send|execute|dispatch)\b[^.]{0,30}\bcommand(s)?\b|\bcommand(s|ed|ing)?\b[^.]{0,40}\b(valve|breaker|setpoint|turbine|fuel|plc|dcs|scada|governor)\b"),
    ]
]

_MONTHS = (r"(January|February|March|April|May|June|July|August|September|October|November|December|"
           r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)")
DATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    re.compile(r"\b20\d\d/\d\d/\d\d\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/20\d\d\b"),
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(st|nd|rd|th)?(,?\s+20\d\d)?\b"),
    re.compile(rf"\b\d{{1,2}}(st|nd|rd|th)?\s+(of\s+)?{_MONTHS}\.?(,?\s+20\d\d)?\b"),
]


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
    out = [("title", report.title), ("summary", report.summary)]
    for i, o in enumerate(report.observations):
        out.append((f"observations[{i}].statement", o.statement))
    for i, h in enumerate(report.hypotheses):
        out.append((f"hypotheses[{i}].name", h.name))
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

    for where, text in _texts(report):
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
