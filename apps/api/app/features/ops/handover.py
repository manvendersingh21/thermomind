"""Shift handover draft: structured case list -> Muse Spark (one call + one bounded rewrite) -> validated
draft, else a deterministic fallback. Persisted to the ``handover_notes`` table (never touches investigations).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from app import config
from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.features.ops.schemas import (HANDOVER_STATUS, OFFLINE_LABEL, HandoverCaseRef, HandoverDraft,
                                      HandoverItem, HandoverNote, HandoverNoteSummary, WatchItem)
from app.schemas import Investigation

log = logging.getLogger("thermomind.ops.handover")

# Default 10000 (the original spec said 3000): muse-spark-1.3 reasoning tokens count against max_tokens, so a long
# case list can truncate; override with OPS_HANDOVER_MAX_TOKENS (truncation is caught by the validator -> rewrite -> fallback).
MAX_TOKENS = int(os.getenv("OPS_HANDOVER_MAX_TOKENS", "10000"))
MAX_STORED_NOTES = 500  # handover_notes retention (newest rows kept)
CASE_ID_RE = re.compile(r"\bcase_[A-Za-z0-9]+\b")

SYSTEM_PROMPT = (
    "Draft a shift handover note for a gas-turbine plant from the structured case list; cite case ids; "
    "distinguish real-only windows from synthetic overlays; do not invent events, times, readings or actions; "
    "no control instructions; mark the note DRAFT — requires shift supervisor sign-off.\n\n"
    "Context: ThermoMind is a read-only decision-support prototype on the public UCI gas-turbine dataset "
    "(real hourly aggregates from an undisclosed Turkish plant, no row timestamps; windows are identified as "
    "source_year + sample index). Cases labelled synthetic_overlay are demonstration scenarios layered on real "
    "rows, not plant events. Every report is a draft requiring human review.\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '{"headline": str, "open_items": [{"case_id": str, "text": str}], '
    '"watch_list": [{"case_id": str|null, "text": str}], "completed": [{"case_id": str, "text": str}], '
    '"caveats": [str]}\n'
    "Rules: open_items = cases or work requests still awaiting human review/action; completed = cases with a "
    "recorded human review decision; watch_list = items to keep an eye on (use case_id null only for the "
    "system health flags given). Every case_id you use must appear in the provided case list. Say 'REAL DATA' "
    "or 'SYNTHETIC OVERLAY' for each case. Do not write calendar dates or clock times; do not recommend "
    "operating the plant (no valves, setpoints, fuel, trips, shutdowns, bypasses, overrides or commands) — "
    "phrase follow-ups as engineer review checks.\n"
    "Be brief: this is transcription of the given facts, not analysis. Headline <= 30 words; each item text "
    "<= 25 words and about exactly one case; at most 5 caveats. Output compact JSON."
)
SCHEMA_REMINDER = ('Required keys: "headline" (string), "open_items" [{"case_id","text"}], '
                   '"watch_list" [{"case_id" or null,"text"}], "completed" [{"case_id","text"}], "caveats" [string].')


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- storage
_SCHEMA = """
CREATE TABLE IF NOT EXISTS handover_notes (
    note_id    TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    hours      INTEGER NOT NULL,
    mode       TEXT NOT NULL,
    note_hash  TEXT NOT NULL,
    json       TEXT NOT NULL
)
"""


class HandoverStore:
    """SQLite table ``handover_notes`` (same DB file as investigations; only this table is written)."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path) if db_path is not None else None
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    @property
    def db_path(self) -> Path:
        return self._db_path if self._db_path is not None else Path(config.DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        return conn

    def save(self, note: HandoverNote) -> HandoverNote:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO handover_notes (note_id, created_at, hours, mode, note_hash, json) VALUES (?,?,?,?,?,?)",
                (note.note_id, note.created_at_utc, note.hours, note.mode, note.note_hash, note.model_dump_json()),
            )
            conn.execute(  # retention: keep only the newest MAX_STORED_NOTES rows
                "DELETE FROM handover_notes WHERE rowid NOT IN "
                "(SELECT rowid FROM handover_notes ORDER BY created_at DESC, rowid DESC LIMIT ?)", (MAX_STORED_NOTES,))
        return note

    def get(self, note_id: str) -> HandoverNote:
        with self._connect() as conn:
            row = conn.execute("SELECT json FROM handover_notes WHERE note_id = ?", (note_id,)).fetchone()
        if row is None:
            raise KeyError(f"handover note '{note_id}' not found")
        return HandoverNote.model_validate_json(row[0])

    def list(self, limit: int = 50) -> list[HandoverNote]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT json FROM handover_notes ORDER BY created_at DESC, rowid DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [HandoverNote.model_validate_json(r[0]) for r in rows]


def summarize(note: HandoverNote) -> HandoverNoteSummary:
    return HandoverNoteSummary(note_id=note.note_id, created_at_utc=note.created_at_utc, hours=note.hours,
                               persona=note.persona, mode=note.mode, meta_used=note.meta_used,
                               source_label=note.source_label, headline=note.draft.headline,
                               case_count=len(note.cases), note_hash=note.note_hash)


# ----------------------------------------------------------------------------- context
def rank1(inv: Investigation) -> tuple[Optional[str], Optional[str]]:
    """(hypothesis key or name, status) of the rank-1 hypothesis; deterministic top hypothesis as fallback."""
    if inv.report is not None and inv.report.hypotheses:
        top = sorted(inv.report.hypotheses, key=lambda h: h.rank)[0]
        return (top.key or top.name), top.status
    tops = (inv.deterministic_summary or {}).get("top_hypotheses") or []
    if tops and isinstance(tops[0], dict) and tops[0].get("hypothesis_key"):
        return str(tops[0]["hypothesis_key"]), "deterministic_heuristic"
    return None, None


def window_label(inv: Investigation) -> str:
    w = inv.window
    return f"{w.source_year} • samples {w.start}–{w.end - 1}"


def case_ref(inv: Investigation) -> HandoverCaseRef:
    key, status = rank1(inv)
    return HandoverCaseRef(
        case_id=inv.case_id, created_at_utc=inv.created_at_utc, status=inv.status, mode=inv.mode,
        scenario_id=inv.scenario.scenario_id, scenario_title=inv.scenario.title,
        scenario_label=inv.scenario_label, synthetic=bool(inv.scenario.synthetic or inv.scenario_label == "synthetic_overlay"),
        window=window_label(inv), severity=(inv.report.severity if inv.report else None),
        rank1_hypothesis=key, rank1_status=status, report_title=(inv.report.title if inv.report else None),
        review_decision=(inv.review.decision if inv.review else None),
        reviewer=(inv.review.reviewer if inv.review else None),
    )


def select_cases(investigations: Iterable[Investigation], hours: int, now: datetime) -> list[Investigation]:
    start = now - timedelta(hours=int(hours))
    out = []
    for inv in investigations:
        ts = parse_ts(inv.created_at_utc)
        if ts is not None and start <= ts <= now + timedelta(minutes=5):
            out.append(inv)
    out.sort(key=lambda i: i.created_at_utc, reverse=True)
    return out


def _wr_dict(wr: Any) -> dict[str, Any]:
    d = wr.model_dump() if hasattr(wr, "model_dump") else dict(wr)
    return {k: d.get(k) for k in ("id", "case_id", "assigned_persona", "status", "title", "severity",
                                  "hypothesis_key", "scenario_label", "synthetic")}


def _compact_case(c: HandoverCaseRef) -> dict[str, Any]:
    return {"case_id": c.case_id, "data": "SYNTHETIC OVERLAY" if c.synthetic else "REAL DATA",
            "scenario": c.scenario_title, "window": c.window, "status": c.status, "severity": c.severity,
            "rank1": c.rank1_hypothesis, "rank1_status": c.rank1_status,
            "review": c.review_decision or "awaiting human review"}


def build_context(cases: list[HandoverCaseRef], work_requests: list[dict[str, Any]],
                  health: dict[str, Any], hours: int, persona: Optional[str]) -> dict[str, Any]:
    return {
        "shift_window_hours": hours,
        "prepared_for_persona": persona,
        "case_count": len(cases),
        "real_only_cases": sum(1 for c in cases if not c.synthetic),
        "synthetic_overlay_cases": sum(1 for c in cases if c.synthetic),
        "cases": [_compact_case(c) for c in cases],
        "open_work_requests": [{k: w.get(k) for k in ("id", "case_id", "assigned_persona", "status", "title")}
                               for w in work_requests],
        "system_health_flags": {k: health.get(k) for k in ("data_ready", "model_ready", "meta_configured", "blockers")
                                if k in health},
    }


# ----------------------------------------------------------------------------- validation
def _texts(d: HandoverDraft) -> list[tuple[str, str]]:
    out = [("headline", d.headline)]
    for name in ("open_items", "watch_list", "completed"):
        for i, it in enumerate(getattr(d, name)):
            out.append((f"{name}[{i}].text", it.text))
    out += [(f"caveats[{i}]", c) for i, c in enumerate(d.caveats)]
    return out


def scan_unsafe(where: str, text: str) -> list[str]:
    errs = []
    for label, pat in UNSAFE_PATTERNS:
        if pat.search(text or ""):
            errs.append(f"unsafe_instruction: '{label}' pattern found in {where}: control actions are forbidden; "
                        f"rephrase as an engineer review check or remove")
            break
    for pat in DATE_PATTERNS:
        m = pat.search(text or "")
        if m:
            errs.append(f"fabricated_date: '{m.group(0)}' in {where}: do not write calendar dates; refer to case "
                        f"ids and source_year + sample index only")
            break
    return errs


def validate_draft(raw: Any, allowed_case_ids: set[str]) -> tuple[Optional[HandoverDraft], list[str]]:
    data = raw if isinstance(raw, dict) else extract_json(raw or "")
    if data is None:
        return None, ["response is not a JSON object (expected the handover JSON object only, no prose)"]
    try:
        draft = HandoverDraft.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errors: list[str] = []
    cited: set[str] = set()
    for it in [*draft.open_items, *draft.completed]:
        cited.add(it.case_id)
    for w in draft.watch_list:
        if w.case_id:
            cited.add(w.case_id)
    for _, text in _texts(draft):
        cited.update(CASE_ID_RE.findall(text or ""))
    unknown = sorted(c for c in cited if c not in allowed_case_ids)
    if unknown:
        errors.append(f"unknown case ids cited: {unknown}; allowed: {sorted(allowed_case_ids)}")
    for where, text in _texts(draft):
        errors += scan_unsafe(where, text)
    return (draft if not errors else None), errors


def ensure_draft_caveat(draft: HandoverDraft) -> HandoverDraft:
    if any("DRAFT" in c for c in draft.caveats):
        return draft
    return draft.model_copy(update={"caveats": [*draft.caveats, f"{HANDOVER_STATUS} (added by server)."]})


# ----------------------------------------------------------------------------- fallback
def _tag(c: HandoverCaseRef) -> str:
    return "SYNTHETIC OVERLAY" if c.synthetic else "REAL DATA"


def fallback_draft(cases: list[HandoverCaseRef], work_requests: list[dict[str, Any]], health: dict[str, Any],
                   hours: int, source_label: str) -> HandoverDraft:
    awaiting = [c for c in cases if c.review_decision in (None, "more_data_requested")]
    reviewed = [c for c in cases if c.review_decision in ("accepted", "rejected")]
    open_items: list[HandoverItem] = []
    watch: list[WatchItem] = []
    for c in awaiting:
        hyp = f"rank-1 hypothesis '{c.rank1_hypothesis}' ({c.rank1_status})" if c.rank1_hypothesis else "no ranked hypothesis"
        sev = f"severity {c.severity}" if c.severity else "no validated report"
        state = "more data requested" if c.review_decision == "more_data_requested" else "awaiting human review"
        open_items.append(HandoverItem(case_id=c.case_id, text=(
            f"[{_tag(c)}] {c.scenario_title}, {c.window}: {hyp}, {sev}, status {c.status}; {state}.")))
        if c.status in ("needs_review", "failed") or c.severity == "urgent_review":
            watch.append(WatchItem(case_id=c.case_id, text=(
                f"[{_tag(c)}] case status {c.status}, severity {c.severity or 'n/a'}: confirm an engineer picks it up.")))
    for wr in work_requests:
        open_items.append(HandoverItem(case_id=str(wr.get("case_id")), text=(
            f"Work request {wr.get('id')} ({wr.get('status')}) assigned to {wr.get('assigned_persona')}: "
            f"{str(wr.get('title') or '')[:200]}")))
    completed = [HandoverItem(case_id=c.case_id, text=(
        f"[{_tag(c)}] {c.scenario_title}, {c.window}: review recorded '{c.review_decision}' by {c.reviewer}."))
        for c in reviewed]
    for b in health.get("blockers") or []:
        watch.append(WatchItem(case_id=None, text=f"System health: {b}"))
    if health and health.get("meta_configured") is False:
        watch.append(WatchItem(case_id=None, text="System health: Meta key not configured; investigations run as offline previews."))
    n_real = sum(1 for c in cases if not c.synthetic)
    headline = (f"DRAFT: {len(cases)} case(s) in the last {hours} h ({n_real} real-only, {len(cases) - n_real} "
                f"synthetic overlay); {len(awaiting)} awaiting human review; {len(work_requests)} open work request(s).")
    caveats = [
        f"{HANDOVER_STATUS}.",
        f"Source: {source_label}. Built deterministically from stored case records; no model wording.",
        "Synthetic-overlay cases are demonstration scenarios on real UCI rows, not plant events.",
        "UCI data has no row timestamps; windows are source_year + sample index.",
        "Read-only decision support; no control actions are implied.",
    ]
    return HandoverDraft(headline=headline, open_items=open_items, watch_list=watch, completed=completed,
                         caveats=caveats)


def note_hash(note: HandoverNote) -> str:
    payload = note.model_dump(mode="json", exclude={"note_hash"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------- generation
def _add_tokens(acc: dict[str, int], usage: dict[str, Any]) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int):
            acc[k] = acc.get(k, 0) + v


def generate_handover(*, hours: int, persona: Optional[str], investigations: Iterable[Investigation],
                      client: Any, store: HandoverStore, work_requests: Optional[list[Any]] = None,
                      work_requests_available: bool = False, health: Optional[dict[str, Any]] = None,
                      now: Optional[datetime] = None) -> HandoverNote:
    now = now or now_utc()
    all_invs = list(investigations)
    known_ids = {i.case_id for i in all_invs}
    in_window = select_cases(all_invs, hours, now)
    wrs = [_wr_dict(w) for w in (work_requests or [])]
    wrs = [w for w in wrs if w.get("status") in ("open", "acknowledged") and w.get("case_id") in known_ids]
    window_ids = {i.case_id for i in in_window}
    # cases referenced only by an open work request are in scope too (they exist in the store)
    extra = [i for i in all_invs if i.case_id not in window_ids and any(w["case_id"] == i.case_id for w in wrs)]
    cases = [case_ref(i) for i in [*in_window, *extra]]
    allowed = {c.case_id for c in cases}
    health = dict(health or {})
    context = build_context(cases, wrs, health, hours, persona)

    errors_seen: list[str] = []
    meta_calls, latency, tokens = 0, 0, {}
    draft: Optional[HandoverDraft] = None
    rewrite_used = False
    fallback_reason: Optional[str] = None
    model_name: Optional[str] = None
    live = client is not None and bool(getattr(client, "configured", False))

    if not live:
        fallback_reason = "Meta client not configured"
    elif not cases and not wrs:
        fallback_reason = f"no cases in the last {hours} h and no open work requests; Meta not called"
    else:
        from app.agent.meta_client import MetaClientError

        model_name = getattr(client, "model", None)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": "Structured case list (JSON):\n"
                                 + json.dumps(context, ensure_ascii=False, default=str)}]
        try:
            res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
            meta_calls += 1
            latency += int(res.latency_ms or 0)
            _add_tokens(tokens, res.usage)
            model_name = res.model or model_name
            content = res.message.get("content") or ""
            draft, errs = validate_draft(content, allowed)
            if draft is None and res.finish_reason == "length" and not content:
                errs = ["response truncated (finish_reason=length); return the compact JSON object only"] + errs
            errors_seen += errs
            if draft is None:
                rewrite_used = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "Your draft was rejected by the validator. Fix ALL of these and return ONLY the corrected "
                    "JSON object (" + SCHEMA_REMINDER + "):\n" + "\n".join(f"- {e}" for e in errs))})
                res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
                meta_calls += 1
                latency += int(res.latency_ms or 0)
                _add_tokens(tokens, res.usage)
                draft, errs2 = validate_draft(res.message.get("content") or "", allowed)
                errors_seen += [f"rewrite: {e}" for e in errs2]
                if draft is None:
                    fallback_reason = "Meta draft rejected after one bounded rewrite"
        except MetaClientError as exc:
            fallback_reason = f"Meta call failed: {str(exc)[:200]}"
            draft = None

    if draft is not None:
        mode, meta_used = "meta_live", True
        source_label = f"Meta Muse Spark draft ({model_name or config.META_MODEL}), validated"
        draft = ensure_draft_caveat(draft)
    else:
        mode, meta_used = "offline_fallback", False
        source_label = OFFLINE_LABEL if meta_calls == 0 else (
            f"deterministic fallback draft — Meta was called {meta_calls}x but its text was rejected and is not used")
        draft = fallback_draft(cases, wrs, health, hours, source_label)
        # the fallback is built from stored records, but it goes through the same scan
        ok, fb_errs = validate_draft(draft.model_dump(), allowed)
        if ok is None:  # pragma: no cover - defensive: never persist an unsafe note
            log.warning("fallback handover failed validation: %s", fb_errs)
            draft = HandoverDraft(headline=f"DRAFT: {len(cases)} case(s) in the last {hours} h; see case list.",
                                  caveats=[f"{HANDOVER_STATUS}.", f"Source: {source_label}."])

    note = HandoverNote(
        note_id=f"ho_{secrets.token_hex(6)}", created_at_utc=iso(now), hours=int(hours), persona=persona,
        window_start_utc=iso(now - timedelta(hours=int(hours))), window_end_utc=iso(now), mode=mode,
        meta_used=meta_used, meta_model=(model_name if meta_calls else None), meta_calls=meta_calls,
        source_label=source_label, rewrite_used=rewrite_used, fallback_reason=(None if meta_used else fallback_reason),
        validation_errors=[e[:500] for e in errors_seen][:20], draft=draft, cases=cases,
        work_requests_included=len(wrs), work_requests_available=bool(work_requests_available),
        health_flags=health, latency_ms=(latency if meta_calls else None), tokens=tokens,
    )
    note = note.model_copy(update={"note_hash": note_hash(note)})
    store.save(note)
    log.info("handover %s mode=%s meta_calls=%d cases=%d", note.note_id, note.mode, meta_calls, len(cases))
    return note
