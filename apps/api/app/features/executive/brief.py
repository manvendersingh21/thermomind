"""Executive brief: overview payload -> ONE Muse Spark call (+ at most one bounded rewrite) -> validated draft,
else a deterministic, labelled fallback. Persisted to the ``executive_briefs`` table (only table this writes).

Validator: unsafe-pattern scan (report_validator.UNSAFE_PATTERNS), fabricated dates (DATE_PATTERNS), financial
claims (currency amounts / "saves"), case ids must exist in the payload, and EVERY number in the brief must appear
in the overview payload the model was given (regex over numbers, with rounding tolerance).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from app import config
from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.features.executive.schemas import (BRIEF_DISCLAIMER, OFFLINE_LABEL, BriefDraft, DecisionNeeded,
                                            ExecutiveBrief, ExecutiveOverview)

log = logging.getLogger("thermomind.executive.brief")

MAX_TOKENS = int(os.getenv("EXECUTIVE_BRIEF_MAX_TOKENS", "8000"))
MAX_STORED = 500
CASE_ID_RE = re.compile(r"\bcase_[A-Za-z0-9]+\b")
# numbers: 1,234.5 / 12.5 / -3 / 85% ; identifiers such as case ids, ev_ ids, S02_ and T01_ are stripped first
NUMBER_RE = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])[-−]?\d+(?:\.\d+)?")
IDENT_RE = re.compile(r"\b(?:case|ev|ho|eb|wr|drill|delib)_[A-Za-z0-9_]+\b|\b[A-Z]{1,3}\d{2}_[A-Z0-9_]+\b|\b[A-Za-z]+\d+[A-Za-z]*\b")
FINANCIAL_RE = re.compile(r"[$€£¥]|\b(?:USD|EUR|GBP)\b|\b(?:will|would|could|can|to)\s+save\b|\bsaves\b|\bsaved\b"
                          r"|\bsavings\s+of\b|\b(?:ROI|payback)\s+of\b", re.IGNORECASE)
# numbers that are part of the brief's own structure, not data claims
STRUCTURAL_NUMBERS = {30.0}
PERSONAS = ("plant_manager", "shift_supervisor", "control_room_operator", "performance_engineer",
            "reliability_engineer", "mechanical_maintenance_engineer", "ic_engineer", "electrical_engineer",
            "environmental_engineer", "hse_officer", "oem_field_service", "ceo")

SYSTEM_PROMPT = (
    "You draft a one-page executive brief for the CEO of a power-generation company from the JSON overview of a "
    "read-only gas-turbine decision-support prototype (ThermoMind). The CEO cares about availability and "
    "forced-outage risk, heat rate and fuel cost, O&M spend and overhaul timing, emissions compliance exposure, "
    "grid-services revenue, safety and OT security, knowledge loss as staff retire, and decision speed with an "
    "audit trail.\n"
    "Facts: the data are public UCI hourly aggregates from one undisclosed plant (2011-2015, no timestamps); "
    "each KPI has a provenance (real, model_derived, simulated, assumption, prototype_metric) and a caveat you "
    "must respect; the thermal model is simulated; grid figures depend on an assumed nameplate; decision metrics "
    "come from this prototype's own store.\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '{"headline": str, "situation": str, "risks": [str], '
    '"decisions_needed": [{"decision": str, "owner_persona": str, "why": str}], '
    '"money_and_time_caveats": [str], "next_30_days": [str]}\n'
    "Hard rules (a validator enforces them; violations are rejected):\n"
    "1. Every number you write must appear in the overview JSON (you may round it). Do not compute new numbers, "
    "totals, percentages, prices, currency amounts or savings. Prefer words over numbers when unsure.\n"
    "2. No calendar dates, clock times or weekdays.\n"
    "3. No control instructions (no valves, setpoints, fuel, load, trips, shutdowns, bypasses, overrides or "
    "commands); decisions are about reviews, approvals, pilots, staffing and priorities.\n"
    "4. Cite only case ids listed in the overview. State provenance in plain words (e.g. 'simulated', "
    "'model-derived proxy').\n"
    "5. owner_persona must be one of: " + ", ".join(PERSONAS) + ".\n"
    "6. No financial outcome is claimed: money_and_time_caveats explains what is NOT known in money and time terms.\n"
    "Be brief: headline <= 25 words; situation <= 80 words; at most 5 items per list; each item <= 30 words. "
    "Output compact JSON."
)
SCHEMA_REMINDER = ('Required keys: "headline", "situation", "risks" [str], "decisions_needed" '
                   '[{"decision","owner_persona","why"}], "money_and_time_caveats" [str], "next_30_days" [str].')


# ----------------------------------------------------------------------------- storage
_SCHEMA = """
CREATE TABLE IF NOT EXISTS executive_briefs (
    brief_id   TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    year       INTEGER NOT NULL,
    mode       TEXT NOT NULL,
    brief_hash TEXT NOT NULL,
    json       TEXT NOT NULL
)
"""


class BriefStore:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path) if db_path is not None else None

    @property
    def db_path(self) -> Path:
        return self._db_path if self._db_path is not None else Path(config.DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        return conn

    def save(self, b: ExecutiveBrief) -> ExecutiveBrief:
        with self._connect() as conn:
            conn.execute("INSERT INTO executive_briefs (brief_id, created_at, year, mode, brief_hash, json) "
                         "VALUES (?,?,?,?,?,?)",
                         (b.brief_id, b.created_at_utc, b.year, b.mode, b.brief_hash, b.model_dump_json()))
            conn.execute("DELETE FROM executive_briefs WHERE rowid NOT IN "
                         "(SELECT rowid FROM executive_briefs ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                         (MAX_STORED,))
        return b

    def get(self, brief_id: str) -> ExecutiveBrief:
        with self._connect() as conn:
            row = conn.execute("SELECT json FROM executive_briefs WHERE brief_id=?", (brief_id,)).fetchone()
        if row is None:
            raise KeyError(f"executive brief '{brief_id}' not found")
        return ExecutiveBrief.model_validate_json(row[0])

    def list(self, limit: int = 20) -> list[ExecutiveBrief]:
        with self._connect() as conn:
            rows = conn.execute("SELECT json FROM executive_briefs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                (int(limit),)).fetchall()
        return [ExecutiveBrief.model_validate_json(r[0]) for r in rows]


# ----------------------------------------------------------------------------- context + number whitelist
def build_context(ov: ExecutiveOverview) -> dict[str, Any]:
    return {
        "dataset_id": ov.dataset_id,
        "source_year": ov.year,
        "needs_attention": [{"title": a.title, "detail": a.detail, "owner_persona": a.persona, "rule": a.rule,
                             "case_ids": a.case_ids} for a in ov.attention],
        "kpis": [{"key": k.key, "group": k.group, "label": k.label, "value": k.value, "unit": k.unit,
                  "provenance": k.provenance, "caveat": k.caveat, "available": k.available,
                  "detail": {dk: dv for dk, dv in k.detail.items() if not isinstance(dv, (list, dict))}}
                 for k in ov.kpis],
        "open_cases": [c.model_dump() for c in ov.open_cases],
        "sources_unavailable": ov.sources_unavailable,
    }


def _parse_num(tok: str) -> Optional[float]:
    try:
        v = float(tok.replace(",", "").replace("−", "-"))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _strip_idents(text: str) -> str:
    return IDENT_RE.sub(" ", text or "")


def numbers_in_text(text: str) -> list[tuple[str, float]]:
    out = []
    for m in NUMBER_RE.finditer(_strip_idents(text)):
        v = _parse_num(m.group(0))
        if v is not None:
            out.append((m.group(0), v))
    return out


def payload_numbers(obj: Any) -> set[float]:
    """All numbers in the payload: numeric values plus numbers written inside strings."""
    acc: set[float] = set()

    def walk(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            if math.isfinite(float(x)):
                acc.add(float(x))
            return
        if isinstance(x, str):
            for _, v in numbers_in_text(x):
                acc.add(v)
            return
        if isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
            return
        if isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(obj)
    return acc


def _decimals(tok: str) -> int:
    t = tok.replace(",", "")
    return len(t.split(".", 1)[1]) if "." in t else 0


def number_supported(tok: str, value: float, allowed: Iterable[float]) -> bool:
    if value in STRUCTURAL_NUMBERS:
        return True
    tol_round = 0.5 * 10 ** (-_decimals(tok)) + 1e-9
    for p in allowed:
        for cand in (p, abs(p)):
            if abs(abs(value) - cand) <= max(tol_round, 0.005 * abs(cand)):
                return True
    return False


# ----------------------------------------------------------------------------- validation
def _texts(d: BriefDraft) -> list[tuple[str, str]]:
    out = [("headline", d.headline), ("situation", d.situation)]
    out += [(f"risks[{i}]", t) for i, t in enumerate(d.risks)]
    for i, dn in enumerate(d.decisions_needed):
        out += [(f"decisions_needed[{i}].decision", dn.decision), (f"decisions_needed[{i}].why", dn.why)]
    out += [(f"money_and_time_caveats[{i}]", t) for i, t in enumerate(d.money_and_time_caveats)]
    out += [(f"next_30_days[{i}]", t) for i, t in enumerate(d.next_30_days)]
    return out


def validate_brief(raw: Any, allowed_numbers: set[float], allowed_case_ids: set[str]
                   ) -> tuple[Optional[BriefDraft], list[str]]:
    data = raw if isinstance(raw, dict) else extract_json(raw or "")
    if data is None:
        return None, ["response is not a JSON object (expected the brief JSON object only, no prose)"]
    try:
        draft = BriefDraft.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errors: list[str] = []
    for i, dn in enumerate(draft.decisions_needed):
        if dn.owner_persona and dn.owner_persona not in PERSONAS:
            errors.append(f"decisions_needed[{i}].owner_persona '{dn.owner_persona}' unknown; use one of {list(PERSONAS)}")
    cited: set[str] = set()
    for where, text in _texts(draft):
        cited.update(CASE_ID_RE.findall(text or ""))
        for label, pat in UNSAFE_PATTERNS:
            if pat.search(text or ""):
                errors.append(f"unsafe_instruction: '{label}' pattern in {where}; control actions are forbidden")
                break
        for pat in DATE_PATTERNS:
            m = pat.search(text or "")
            if m:
                errors.append(f"fabricated_date: '{m.group(0)}' in {where}; do not write dates or clock times")
                break
        fm = FINANCIAL_RE.search(text or "")
        if fm:
            errors.append(f"financial_claim: '{fm.group(0)}' in {where}; no currency amounts or savings claims")
        bad = [tok for tok, v in numbers_in_text(text) if not number_supported(tok, v, allowed_numbers)]
        if bad:
            errors.append(f"number_not_in_payload: {bad[:6]} in {where}; every number must appear in the overview "
                          f"JSON (round if needed) or be replaced by words")
    unknown = sorted(c for c in cited if c not in allowed_case_ids)
    if unknown:
        errors.append(f"unknown case ids cited: {unknown}; allowed: {sorted(allowed_case_ids)}")
    return (draft if not errors else None), errors


# ----------------------------------------------------------------------------- fallback
def fallback_brief(ov: ExecutiveOverview) -> BriefDraft:
    by = {k.key: k for k in ov.kpis}
    att = [a for a in ov.attention if a.severity == "attention"]
    headline = (f"{len(att)} item(s) need attention in the {ov.year} prototype overview"
                if att else f"No rule-based attention item in the {ov.year} prototype overview")

    def val(key: str) -> str:
        k = by.get(key)
        if k is None or not k.available or k.value is None:
            return "unavailable"
        return f"{k.value} {k.unit}".strip()

    situation = (f"Output vs expected (model-derived proxy): {val('tey_residual_year_mean')}. "
                 f"Instrument health ok/watch/check: {val('instrument_health')}. "
                 f"Smallest simulated thermal margin: {val('thermal_min_margin')}. "
                 f"Emissions screening excursions: {val('emissions_excursions')}.")
    risks = [f"{a.title} ({a.persona_name})." for a in att][:5] or [
        "No rule fired; that is not evidence of no risk, because the data set has no fault labels."]
    decisions = [DecisionNeeded(decision=f"Assign and review: {a.title}", owner_persona=a.persona,
                                why=a.detail) for a in ov.attention][:5]
    caveats = ["No savings, cost or revenue is computed or claimed; the planner economics use default assumptions.",
               "Decision-speed figures come from this prototype's store, not from plant staff time.",
               "Public data from one plant without timestamps; thermal values are simulated."]
    nxt = ["Name an owner for each attention item and record the human decision in ThermoMind.",
           "Agree pilot success metrics (engineer time per case, acceptance rate, false-review rate)."]
    return BriefDraft(headline=headline, situation=situation, risks=risks, decisions_needed=decisions,
                      money_and_time_caveats=caveats, next_30_days=nxt)


def _hash(b: ExecutiveBrief) -> str:
    payload = b.model_dump(mode="json", exclude={"brief_hash"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _add_tokens(acc: dict[str, int], usage: dict[str, Any]) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int):
            acc[k] = acc.get(k, 0) + v


# ----------------------------------------------------------------------------- generation
def generate_brief(ov: ExecutiveOverview, *, client: Any, store: BriefStore, now_utc: str) -> ExecutiveBrief:
    context = build_context(ov)
    allowed_nums = payload_numbers(context)
    allowed_cases = {c.case_id for c in ov.open_cases} | {cid for a in ov.attention for cid in a.case_ids}
    errors_seen: list[str] = []
    meta_calls, latency, tokens = 0, 0, {}
    draft: Optional[BriefDraft] = None
    rewrite_used = False
    fallback_reason: Optional[str] = None
    model_name: Optional[str] = None
    live = client is not None and bool(getattr(client, "configured", False))
    if not live:
        fallback_reason = "Meta client not configured"
    else:
        from app.agent.meta_client import MetaClientError

        model_name = getattr(client, "model", None)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": "Executive overview (JSON):\n"
                                 + json.dumps(context, ensure_ascii=False, default=str)}]
        try:
            res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
            meta_calls += 1
            latency += int(res.latency_ms or 0)
            _add_tokens(tokens, res.usage)
            model_name = res.model or model_name
            content = res.message.get("content") or ""
            draft, errs = validate_brief(content, allowed_nums, allowed_cases)
            if draft is None and res.finish_reason == "length" and not content:
                errs = ["response truncated (finish_reason=length); return the compact JSON object only"] + errs
            errors_seen += errs
            if draft is None:
                rewrite_used = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "Your brief was rejected by the validator. Fix ALL of these and return ONLY the corrected JSON "
                    "object (" + SCHEMA_REMINDER + "):\n" + "\n".join(f"- {e}" for e in errs))})
                res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
                meta_calls += 1
                latency += int(res.latency_ms or 0)
                _add_tokens(tokens, res.usage)
                draft, errs2 = validate_brief(res.message.get("content") or "", allowed_nums, allowed_cases)
                errors_seen += [f"rewrite: {e}" for e in errs2]
                if draft is None:
                    fallback_reason = "Meta brief rejected after one bounded rewrite"
        except MetaClientError as exc:
            fallback_reason = f"Meta call failed: {str(exc)[:200]}"
            draft = None
    if draft is not None:
        mode, meta_used = "meta_live", True
        source_label = f"Meta Muse Spark draft ({model_name or config.META_MODEL}), validated"
    else:
        mode, meta_used = "offline_fallback", False
        source_label = OFFLINE_LABEL if meta_calls == 0 else (
            f"deterministic fallback — Meta was called {meta_calls}x but its text was rejected and is not used")
        draft = fallback_brief(ov)
    b = ExecutiveBrief(
        brief_id=f"eb_{secrets.token_hex(6)}", created_at_utc=now_utc, year=ov.year, dataset_id=ov.dataset_id,
        mode=mode, meta_used=meta_used, meta_model=(model_name if meta_calls else None), meta_calls=meta_calls,
        source_label=source_label, rewrite_used=rewrite_used, fallback_reason=(None if meta_used else fallback_reason),
        validation_errors=[e[:500] for e in errors_seen][:20], brief=draft, disclaimer=BRIEF_DISCLAIMER,
        overview_numbers_checked=len(allowed_nums), latency_ms=(latency if meta_calls else None), tokens=tokens,
    )
    b = b.model_copy(update={"brief_hash": _hash(b)})
    store.save(b)
    log.info("executive brief %s mode=%s meta_calls=%d", b.brief_id, b.mode, meta_calls)
    return b
