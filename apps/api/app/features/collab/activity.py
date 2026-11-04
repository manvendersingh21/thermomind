"""Case activity feed: one read-only timeline for every team, aggregated from existing tables.

Sources (all optional; a missing table/module just yields no items): the investigation record (created,
agent tool calls, validator events, completion, human review), plant work requests + their status history,
simulated in-app notifications, autonomy-policy decisions, what-if sessions on the case, handover notes that
include the case, precedent recall tool calls. Nothing is written.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.features.collab import db
from app.features.collab.schemas import ActivityItem, ActivityResponse

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse(ts: Optional[str]) -> datetime:
    if not ts:
        return _EPOCH
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _persona_kind(pid: str) -> str:
    if pid in ("system", ""):
        return "system"
    try:
        from app.plant.personas import PERSONAS  # guarded

        return "persona" if pid in PERSONAS else "human"
    except Exception:  # noqa: BLE001
        return "human"


def _investigation_items(inv: Any) -> list[ActivityItem]:
    link = f"/investigations/{inv.case_id}"
    tag = "SYNTHETIC OVERLAY" if inv.scenario.synthetic else "REAL DATA"
    w = inv.window
    items = [ActivityItem(ts_utc=inv.created_at_utc, actor="agent:investigator", actor_kind="agent",
                          kind="investigation_created", link=link,
                          summary=f"Case opened: {inv.scenario.title} [{tag}], {w.source_year} samples "
                                  f"{w.start}–{w.end - 1}; {len(inv.evidence or [])} evidence items computed.")]
    events = list(inv.events or [])
    tool_calls = [e for e in events if e.kind == "tool_call"]
    if tool_calls:
        names = sorted({e.tool_name or "?" for e in tool_calls})
        items.append(ActivityItem(ts_utc=tool_calls[-1].ts_utc, actor="agent:investigator", actor_kind="agent",
                                  kind="agent_tool_calls", link=link,
                                  summary=f"{len(tool_calls)} tool call(s): {', '.join(names)[:300]}"))
    for e in events:
        if e.kind == "validation":
            items.append(ActivityItem(ts_utc=e.ts_utc, actor="agent:validator", actor_kind="agent", kind="validator",
                                      link=link, summary=f"Validator {'passed' if e.ok else 'rejected'}: "
                                                         f"{e.summary[:240]}"))
        elif e.kind == "rewrite_requested":
            items.append(ActivityItem(ts_utc=e.ts_utc, actor="agent:validator", actor_kind="agent", kind="validator",
                                      link=link, summary=f"Bounded rewrite requested: {e.summary[:240]}"))
        elif e.kind in ("report_accepted", "fallback"):
            items.append(ActivityItem(ts_utc=e.ts_utc, actor="agent:investigator", actor_kind="agent",
                                      kind="report_accepted" if e.kind == "report_accepted" else "fallback",
                                      link=link, summary=e.summary[:300]))
        elif e.kind == "tool_call" and e.tool_name == "recall_similar_cases":
            items.append(ActivityItem(ts_utc=e.ts_utc, actor="agent:investigator", actor_kind="agent",
                                      kind="precedents_recalled", link=link,
                                      summary=f"Reviewed precedents recalled: {e.summary[:240]}"))
    if inv.completed_at_utc:
        sev = inv.report.severity if inv.report is not None else "no validated report"
        items.append(ActivityItem(ts_utc=inv.completed_at_utc, actor="agent:investigator", actor_kind="agent",
                                  kind="investigation_completed", link=link,
                                  summary=f"Investigation {inv.status} (mode {inv.mode}, {len(tool_calls)} tool calls, "
                                          f"severity {sev}); draft requires human review."))
    if inv.review is not None:
        r = inv.review
        items.append(ActivityItem(ts_utc=r.ts_utc, actor=r.reviewer, actor_kind=_persona_kind(r.reviewer),
                                  kind="review_decision", link=link,
                                  summary=f"Human review: {r.decision}" + (f" — “{r.comment[:200]}”" if r.comment else "")))
    return items


def _work_request_items(case_id: str) -> tuple[list[ActivityItem], bool]:
    if not db.table_exists("plant_work_requests"):  # stay read-only: the plant store would create its tables
        return [], False
    try:
        from app.plant import store as plant_store  # guarded

        wrs = plant_store.list_work_requests(case_id=case_id)
    except Exception:  # noqa: BLE001
        return [], False
    items = []
    for wr in wrs:
        items.append(ActivityItem(ts_utc=wr.created_at_utc, actor="agent:router", actor_kind="agent",
                                  kind="work_request_created", link="/inbox",
                                  summary=f"Work request {wr.id} routed by {wr.routed_by}: {wr.assignment_label}"))
        for h in wr.history[1:]:  # history[0] is the creation entry
            items.append(ActivityItem(ts_utc=h.ts_utc, actor=h.persona, actor_kind=_persona_kind(h.persona),
                                      kind="work_request_status", link="/inbox",
                                      summary=f"Work request {wr.id} → {h.status}"
                                              + (f": “{h.comment[:200]}”" if h.comment else "")))
    return items, True


def _notification_items(case_id: str) -> tuple[list[ActivityItem], bool]:
    if not db.table_exists("plant_notifications"):
        return [], False
    items = []
    for raw in db.read_json_rows("plant_notifications", like=case_id):
        try:
            n = json.loads(raw)
        except ValueError:
            continue
        if n.get("case_id") != case_id:
            continue
        items.append(ActivityItem(ts_utc=n.get("created_at_utc") or "", actor=str(n.get("persona")),
                                  actor_kind="system", kind="notification", link="/inbox",
                                  summary=f"Simulated in-app notification to {n.get('persona')} ({n.get('kind')})"
                                          f"{' · read' if n.get('read') else ''}"))
    return items, True


def _decision_items(case_id: str) -> tuple[list[ActivityItem], bool]:
    try:
        decisions = db.list_decisions(case_id=case_id)
    except Exception:  # noqa: BLE001
        return [], False
    out = []
    for d in decisions:
        human = d.decision == "human_override_reopened"
        out.append(ActivityItem(ts_utc=d.ts_utc, actor=d.actor, actor_kind=_persona_kind(d.actor) if human else "agent",
                                kind="auto_decision", link="/autonomy",
                                summary=f"Policy {d.policy_id}: {d.decision} — {d.reason[:300]}"))
    return out, True


def _whatif_items(case_id: str) -> tuple[list[ActivityItem], bool]:
    if not db.table_exists("whatif_sessions"):
        return [], False
    items = []
    for raw in db.read_json_rows("whatif_sessions", like=case_id):
        try:
            s = json.loads(raw)
        except ValueError:
            continue
        req = s.get("request") or {}
        if req.get("case_id") != case_id:
            continue
        q = f" — “{str(req.get('question'))[:160]}”" if req.get("question") else ""
        items.append(ActivityItem(ts_utc=s.get("created_at_utc") or "", actor=str(s.get("persona")),
                                  actor_kind=_persona_kind(str(s.get("persona"))), kind="whatif_session",
                                  link="/ask", summary=f"Asked the plant: {req.get('measurement')} "
                                                       f"{float(req.get('delta') or 0):+g}{q} "
                                                       f"(session {s.get('session_id')}, {s.get('status')}, "
                                                       f"{s.get('mode')})"))
    return items, True


def _handover_items(case_id: str) -> tuple[list[ActivityItem], bool]:
    if not db.table_exists("handover_notes"):
        return [], False
    items = []
    for raw in db.read_json_rows("handover_notes", like=case_id):
        try:
            n = json.loads(raw)
        except ValueError:
            continue
        cited = {c.get("case_id") for c in n.get("cases") or []}
        if case_id not in cited and case_id not in raw:
            continue
        items.append(ActivityItem(ts_utc=n.get("created_at_utc") or "", actor="agent:handover", actor_kind="agent",
                                  kind="handover_note", link="/ops",
                                  summary=f"Included in shift handover draft {n.get('note_id')} ({n.get('mode')}); "
                                          "requires shift supervisor sign-off."))
    return items, True


def case_activity(case_id: str, get_investigation: Callable[[str], Any]) -> ActivityResponse:
    """KeyError (404) when the case does not exist."""
    inv = get_investigation(case_id)
    items = _investigation_items(inv)
    sources = {"investigation": True}
    for name, fn in (("work_requests", _work_request_items), ("notifications", _notification_items),
                     ("policy_decisions", _decision_items), ("whatif_sessions", _whatif_items),
                     ("handover_notes", _handover_items)):
        try:
            got, ok = fn(case_id)
        except Exception:  # noqa: BLE001 - one broken source must not hide the others
            got, ok = [], False
        items += got
        sources[name] = ok
    items.sort(key=lambda i: _parse(i.ts_utc))  # stable: same-ts items keep source order
    return ActivityResponse(case_id=case_id, items=items, sources=sources)
