"""CMMS draft export: one investigation -> a generic draft work-order (JSON) or CSV. Nothing is submitted."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional

from app.features.ops.schemas import CMMS_ASSET, CMMS_STATUS, CMMS_SYSTEM
from app.schemas import Investigation

PRIORITY = {
    "urgent_review": ("P1", "urgent review"),
    "review": ("P2", "review"),
    "informational": ("P3", "informational"),
}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
CSV_COLUMNS = ["external_ref", "asset", "priority", "priority_label", "title", "description", "task_seq",
               "task_text", "requested_by", "status", "generated_at_utc", "system", "scenario_label", "synthetic"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cited_evidence_ids(inv: Investigation) -> list[str]:
    out: list[str] = []
    if inv.report is None:
        return out
    for o in inv.report.observations:
        out += o.evidence_ids
    for h in inv.report.hypotheses:
        out += h.supporting_evidence_ids + h.contradicting_evidence_ids
    return list(dict.fromkeys(out))


def build_work_order(inv: Investigation, requested_by: str, generated_at: Optional[str] = None) -> dict[str, Any]:
    report = inv.report
    synthetic = bool(inv.scenario.synthetic or inv.scenario_label == "synthetic_overlay")
    tag = "SYNTHETIC OVERLAY" if synthetic else "REAL DATA"
    w = inv.window
    window = f"{w.source_year} • samples {w.start}–{w.end - 1}"
    if report is not None:
        code, label = PRIORITY.get(report.severity, ("P2", "review"))
        top = sorted(report.hypotheses, key=lambda h: h.rank)[0] if report.hypotheses else None
        hyp = (f"Rank-1 hypothesis: {top.name} ({top.key or 'n/a'}, status {top.status}); supporting evidence "
               f"{', '.join(top.supporting_evidence_ids) or 'none'}; contradicting "
               f"{', '.join(top.contradicting_evidence_ids) or 'none'}.") if top else "No ranked hypothesis."
        title = f"[{tag}] {report.title}"
        description = (f"{report.summary}\n{hyp}\nEvidence ids cited in report: "
                       f"{', '.join(cited_evidence_ids(inv)) or 'none'}.\nWindow: {window} (UCI rows, no timestamps). "
                       f"Report status: {report.report_status}.")
        checks = list(report.engineer_review_checks)
    else:
        code, label = "P2", "review (no validated report)"
        title = f"[{tag}] Review case {inv.case_id} — no validated report"
        description = (f"Investigation status {inv.status}; no validated report. Review the deterministic summary "
                       f"and evidence in ThermoMind.\nWindow: {window} (UCI rows, no timestamps).")
        checks = ["Review the deterministic summary and evidence for this case in ThermoMind."]
    tasks = [{"seq": i + 1, "text": t, "type": "engineer_review_check"} for i, t in enumerate(checks)]
    return {
        "work_order_draft": {
            "external_ref": inv.case_id,
            "asset": CMMS_ASSET,
            "priority": code,
            "priority_label": label,
            "title": title[:300],
            "description": description,
            "tasks": tasks,
            "requested_by": requested_by,
            "status": CMMS_STATUS,
            "generated_at_utc": generated_at or _now(),
            "system": CMMS_SYSTEM,
        },
        "provenance": {
            "case_id": inv.case_id,
            "scenario_id": inv.scenario.scenario_id,
            "scenario_label": inv.scenario_label,
            "synthetic": synthetic,
            "window": window,
            "data_source": report.data_source if report else "UCI_GAS_TURBINE_551",
            "investigation_status": inv.status,
            "mode": inv.mode,
            "meta_used": inv.meta_used,
            "report_hash": inv.report_hash,
            "human_review": (inv.review.model_dump() if inv.review else None),
        },
        "notice": ("Draft export only: not submitted to any CMMS. Read-only decision support; tasks are engineer "
                   "review checks, not control actions. Requires human review."),
    }


def safe_cell(value: Any) -> str:
    """Neutralise spreadsheet formula injection: prefix = + - @ (and tab/CR) with a single quote."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(FORMULA_PREFIXES) else s


def work_order_csv(doc: dict[str, Any]) -> str:
    wo, prov = doc["work_order_draft"], doc["provenance"]
    base = {k: wo.get(k) for k in CSV_COLUMNS if k in wo}
    base.update(scenario_label=prov["scenario_label"], synthetic=str(prov["synthetic"]).lower())
    rows = [{**base, "task_seq": t["seq"], "task_text": t["text"]} for t in wo["tasks"]] or [
        {**base, "task_seq": "", "task_text": ""}]
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow([safe_cell(r.get(c)) for c in CSV_COLUMNS])
    return buf.getvalue()
