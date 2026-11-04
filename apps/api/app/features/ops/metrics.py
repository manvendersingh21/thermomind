"""Prototype metrics computed ONLY from stored investigations (this demo database), not pilot results."""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.features.ops.handover import parse_ts
from app.features.ops.schemas import MedianStat, OpsMetrics, RateStat
from app.schemas import Investigation

DEFINITIONS = {
    "live_wall_time_s": "meta_live cases: seconds from the first model_request event to the report_accepted event.",
    "tool_calls_per_live_case": "meta_live cases: number of successful tool_call events.",
    "validator_first_pass_acceptance": "meta_live cases with a validation event: share whose FIRST validation event was ok.",
    "rewrite_rate": "meta_live cases with a validation event: share with a validator rewrite turn "
                    "(rewrite_requested after a failed validation; tool-use nudges excluded).",
    "review_counts": "Human review decisions recorded on cases; 'unreviewed' = no decision yet.",
    "evidence_citations_per_report": "Distinct evidence ids cited by a stored report (observations + hypotheses).",
    "cited_ids_resolving": "Cited evidence ids that resolve to an evidence item stored with the same case.",
    "time_to_review_s": "Reviewed cases: seconds from created_at_utc to the review ts_utc.",
}


def _median(vals: list[float], unit: str) -> MedianStat:
    return MedianStat(median=(round(float(statistics.median(vals)), 3) if vals else None), n=len(vals), unit=unit)


def _rate(num: int, n: int) -> RateStat:
    return RateStat(rate=(round(num / n, 4) if n else None), numerator=num, n=n)


def _secs(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ta, tb = parse_ts(a), parse_ts(b)
    if ta is None or tb is None:
        return None
    d = (tb - ta).total_seconds()
    return d if d >= 0 else None


def _cited(inv: Investigation) -> list[str]:
    if inv.report is None:
        return []
    ids: list[str] = []
    for o in inv.report.observations:
        ids += o.evidence_ids
    for h in inv.report.hypotheses:
        ids += h.supporting_evidence_ids + h.contradicting_evidence_ids
    return list(dict.fromkeys(ids))


def compute_metrics(investigations: Iterable[Investigation], now: Optional[str] = None) -> OpsMetrics:
    invs = list(investigations)
    live = [i for i in invs if i.mode == "meta_live"]
    wall, tools, ttr, cites = [], [], [], []
    first_pass_ok = validated = rewrites = 0
    cited_total = cited_resolved = 0
    for inv in live:
        ev = inv.events
        first_req = next((e for e in ev if e.kind == "model_request"), None)
        accepted = next((e for e in ev if e.kind == "report_accepted"), None)
        if first_req and accepted:
            s = _secs(first_req.ts_utc, accepted.ts_utc)
            if s is not None:
                wall.append(s)
        tools.append(float(sum(1 for e in ev if e.kind == "tool_call" and e.ok)))
        vals = [e for e in ev if e.kind == "validation"]
        if vals:
            validated += 1
            first_pass_ok += int(bool(vals[0].ok))
            first_val_seq = vals[0].seq
            if any(e.kind == "rewrite_requested" and e.seq > first_val_seq for e in ev):
                rewrites += 1
    for inv in invs:
        if inv.report is not None:
            ids = _cited(inv)
            cites.append(float(len(ids)))
            known = {e.evidence_id for e in inv.evidence}
            cited_total += len(ids)
            cited_resolved += sum(1 for x in ids if x in known)
        if inv.review is not None:
            s = _secs(inv.created_at_utc, inv.review.ts_utc)
            if s is not None:
                ttr.append(s)
    reviews = Counter(i.review.decision if i.review else "unreviewed" for i in invs)
    for k in ("accepted", "rejected", "more_data_requested", "unreviewed"):
        reviews.setdefault(k, 0)
    return OpsMetrics(
        generated_at_utc=now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        cases_total=len(invs),
        by_mode=dict(Counter(i.mode for i in invs)),
        by_status=dict(Counter(i.status for i in invs)),
        by_scenario_label=dict(Counter(i.scenario_label for i in invs)),
        live_cases=len(live),
        live_wall_time_s=_median(wall, "s"),
        tool_calls_per_live_case=_median(tools, "tool calls"),
        validator_first_pass_acceptance=_rate(first_pass_ok, validated),
        rewrite_rate=_rate(rewrites, validated),
        review_counts=dict(reviews),
        evidence_citations_per_report=_median(cites, "evidence ids"),
        cited_ids_resolving=_rate(cited_resolved, cited_total),
        time_to_review_s=_median(ttr, "s"),
        definitions=DEFINITIONS,
    )
