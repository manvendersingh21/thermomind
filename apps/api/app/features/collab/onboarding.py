"""Onboarding brief for a new joiner: ONE Muse Spark call (+ one bounded rewrite) over a structured context of
the persona, the subsystem registry, the people they work with and their open items; validated, else a
deterministic fallback (labelled). Persisted to ``onboarding_briefs``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from app import config
from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.features.collab import db
from app.features.collab.schemas import (ONBOARDING_DISCLAIMER, Colleague, OnboardingBrief, OnboardingBriefBody,
                                         PlantPart, WatchItem)
from app.schemas import MEASUREMENT_KEYS, MEASUREMENTS

log = logging.getLogger("thermomind.collab.onboarding")

MAX_TOKENS = int(os.getenv("COLLAB_ONBOARDING_MAX_TOKENS", "8000"))
CASE_ID_RE = re.compile(r"\bcase_[A-Za-z0-9]+\b")
PERSONA_LIKE_RE = re.compile(r"\b[a-z]+(?:_[a-z]+)*_(?:engineer|officer|supervisor|manager|operator|service)\b")
OFFLINE_LABEL = "offline fallback — deterministic brief built from the persona and subsystem registry (no Meta call)"

SYSTEM_PROMPT = (
    "You write an onboarding brief for a new joiner at a gas-turbine plant who will use ThermoMind, a read-only "
    "decision-support prototype on the public UCI gas-turbine dataset (real hourly aggregates from an undisclosed "
    "plant, 2011-2015, no row timestamps, no fault labels). Use ONLY the structured context you are given.\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '{"role_summary": str, "how_the_plant_works": [{"subsystem": str, "explanation": str}], '
    '"what_you_watch": [{"measurement": str, "why": str}], "who_you_work_with": [{"persona": str, "when": str}], '
    '"current_open_items": [str], "first_week_checklist": [str], "disclaimer": str}\n'
    "Rules: subsystem must be a subsystem key from the context; measurement must be a measurement key from the "
    "context; persona must be a persona_id from the context; current_open_items must contain only case ids from "
    "context.open_case_ids (may be empty). Do not invent people, cases, events, numbers or dates; do not write "
    "calendar dates, weekday names or clock times (use 'Day 1', 'Day 2', ...). Never instruct anyone to operate "
    "the plant (no valves, setpoints, load, fuel, trips, starts/stops, isolation, bypasses or commands): the new "
    "joiner reviews, compares, asks and confirms; field work is approved by their supervisor under permit. "
    "Be concise: role_summary <= 60 words; 3-5 subsystems; 3-6 measurements; 3-6 colleagues; 5-8 checklist items, "
    "each <= 25 words. Output compact JSON."
)
SCHEMA_REMINDER = ('Required keys: role_summary (str), how_the_plant_works [{subsystem, explanation}], '
                   'what_you_watch [{measurement, why}], who_you_work_with [{persona, when}], '
                   'current_open_items [case id str], first_week_checklist [str], disclaimer (str).')


def now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ----------------------------------------------------------------------------- providers (patched in tests)
def get_investigations() -> list[Any]:
    from app import services

    return services.get_store().list()


def get_work_requests() -> list[Any]:
    try:
        from app.plant import store as plant_store  # guarded

        return plant_store.list_work_requests()
    except Exception:  # noqa: BLE001
        return []


def get_meta_client() -> Any:
    try:
        from app import services

        client = services.get_meta_client()
        return client if client.configured else None
    except Exception as exc:  # noqa: BLE001
        log.warning("meta client unavailable: %s", type(exc).__name__)
        return None


def _personas() -> dict[str, Any]:
    from app.plant.personas import PERSONAS

    return PERSONAS


def _registry() -> list[dict]:
    from app.plant.subsystems import SUBSYSTEM_REGISTRY

    return list(SUBSYSTEM_REGISTRY)


# ----------------------------------------------------------------------------- context
def build_context(persona_id: str, investigations: Iterable[Any], work_requests: Iterable[Any]) -> dict[str, Any]:
    personas = _personas()
    p = personas[persona_id]  # KeyError -> 404
    from app.plant.personas import ESCALATION_RULES, ROUTING_TABLE

    invs = list(investigations)
    known = {i.case_id for i in invs}
    mine = [w for w in work_requests
            if getattr(w, "status", None) in ("open", "acknowledged") and w.case_id in known
            and (w.assigned_persona == persona_id or persona_id in (w.notified_personas or []))]
    open_ids = list(dict.fromkeys(w.case_id for w in mine))[:12]
    routing = {k: v for k, v in ROUTING_TABLE.items()
               if persona_id in (v.get("assignee"), v.get("supervisor"), *(v.get("cc") or []))}
    return {
        "persona": {"persona_id": p.persona_id, "role": p.role, "description": p.description,
                    "subsystems": p.subsystems, "measurements_watched": p.measurements_watched,
                    "supervisor": p.supervisor, "external": p.external},
        "supervises": [q.persona_id for q in personas.values() if q.supervisor == persona_id],
        "personas": [{"persona_id": q.persona_id, "role": q.role, "description": q.description,
                      "supervisor": q.supervisor} for q in personas.values()],
        "subsystems": [{"key": s["key"], "name": s["name"], "measurements": s["measurements"],
                        "how_it_works": s.get("how_it_works", ""), "owner_persona": s["owner_persona"]}
                       for s in _registry()],
        "measurements": [{"key": m, "name": MEASUREMENTS[m]["name"], "unit": MEASUREMENTS[m]["unit"]}
                         for m in MEASUREMENT_KEYS],
        "routing_rules_involving_you": routing,
        "escalation_rules": ESCALATION_RULES,
        "open_case_ids": open_ids,
        "open_work_requests": [{"id": w.id, "case_id": w.case_id, "status": w.status, "severity": w.severity,
                                "synthetic": w.synthetic, "assigned_persona": w.assigned_persona}
                               for w in mine[:12]],
        "autonomy": "Agents do read-only screening, routing, precedent recall and drafts automatically; humans "
                    "accept/reject reports, acknowledge/close work requests and approve next steps; maintenance, "
                    "switching and plant control are human-only and outside ThermoMind.",
    }


# ----------------------------------------------------------------------------- validation
def _texts(b: OnboardingBriefBody) -> list[tuple[str, str]]:
    out = [("role_summary", b.role_summary)]
    out += [(f"how_the_plant_works[{i}]", x.explanation) for i, x in enumerate(b.how_the_plant_works)]
    out += [(f"what_you_watch[{i}]", x.why) for i, x in enumerate(b.what_you_watch)]
    out += [(f"who_you_work_with[{i}]", x.when) for i, x in enumerate(b.who_you_work_with)]
    out += [(f"first_week_checklist[{i}]", x) for i, x in enumerate(b.first_week_checklist)]
    return out


def scan_text(where: str, text: str) -> list[str]:
    errs = []
    for label, pat in UNSAFE_PATTERNS:
        if pat.search(text or ""):
            errs.append(f"unsafe_instruction: '{label}' pattern in {where}: no plant operation; phrase it as "
                        f"review / compare / ask / confirm")
            break
    for pat in DATE_PATTERNS:
        m = pat.search(text or "")
        if m:
            errs.append(f"fabricated_date: '{m.group(0)}' in {where}: no dates, weekdays or clock times; "
                        f"use 'Day 1', 'Day 2'")
            break
    return errs


def validate_brief(raw: Any, allowed_case_ids: set[str]) -> tuple[Optional[OnboardingBriefBody], list[str]]:
    data = raw if isinstance(raw, dict) else extract_json(raw or "")
    if data is None:
        return None, ["response is not a JSON object (expected the onboarding JSON object only, no prose)"]
    try:
        body = OnboardingBriefBody.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errors: list[str] = []
    personas = set(_personas())
    subsystems = {s["key"] for s in _registry()}
    bad_sub = sorted({x.subsystem for x in body.how_the_plant_works} - subsystems)
    if bad_sub:
        errors.append(f"unknown subsystem ids: {bad_sub}; allowed: {sorted(subsystems)}")
    bad_m = sorted({x.measurement for x in body.what_you_watch} - set(MEASUREMENT_KEYS))
    if bad_m:
        errors.append(f"unknown measurement keys: {bad_m}; allowed: {MEASUREMENT_KEYS}")
    bad_p = sorted({x.persona for x in body.who_you_work_with} - personas)
    cited_cases = set(body.current_open_items)
    for _, text in _texts(body):
        cited_cases.update(CASE_ID_RE.findall(text or ""))
        bad_p += [t for t in PERSONA_LIKE_RE.findall(text or "") if t not in personas]
    if bad_p:
        errors.append(f"unknown persona ids: {sorted(set(bad_p))}; allowed: {sorted(personas)}")
    bad_c = sorted(c for c in cited_cases if c not in allowed_case_ids)
    if bad_c:
        errors.append(f"unknown case ids cited: {bad_c}; allowed: {sorted(allowed_case_ids) or 'none'}")
    if not body.first_week_checklist:
        errors.append("first_week_checklist must not be empty")
    for where, text in _texts(body):
        errors += scan_text(where, text)
    return (body if not errors else None), errors


# ----------------------------------------------------------------------------- fallback
def fallback_brief(ctx: dict[str, Any]) -> OnboardingBriefBody:
    p = ctx["persona"]
    personas = {q["persona_id"]: q for q in ctx["personas"]}
    subs = [s for s in ctx["subsystems"] if s["key"] in p["subsystems"]
            or set(s["measurements"]) & set(p["measurements_watched"])] or ctx["subsystems"]
    parts = [PlantPart(subsystem=s["key"], explanation=s["how_it_works"] or s["name"]) for s in subs[:5]]
    units = {m["key"]: m for m in ctx["measurements"]}
    watch = [WatchItem(measurement=m, why=f"{units[m]['name']} ({units[m]['unit']}) is in your watch list for "
                                         f"the {p['role']} role.") for m in p["measurements_watched"][:6] if m in units]
    colleagues: list[Colleague] = []
    if p["supervisor"]:
        colleagues.append(Colleague(persona=p["supervisor"], when="Your supervisor: approves field work and "
                                                                   "next steps; ask them to verify this guide."))
    for sid in ctx["supervises"][:3]:
        colleagues.append(Colleague(persona=sid, when="You supervise their investigations and approvals."))
    owners = {s["owner_persona"] for s in subs} - {p["persona_id"], p["supervisor"]}
    for oid in sorted(owners)[:3]:
        if oid in personas:
            colleagues.append(Colleague(persona=oid, when="Owns a subsystem you watch; ask them about its evidence."))
    if "control_room_operator" in personas and p["persona_id"] != "control_room_operator":
        colleagues.append(Colleague(persona="control_room_operator", when="Sees every alert first (read-only "
                                                                            "acknowledgement in ThermoMind)."))
    checklist = [
        "Day 1: read the Overview legend (REAL PUBLIC DATA, MODEL-DERIVED, SYNTHETIC OVERLAY, HUMAN REVIEW REQUIRED).",
        "Day 1: open your Inbox and read each work request routed to you with its review checks.",
        "Day 2: open one case and compare its evidence z-scores with the reference window.",
        "Day 2: open the domino map on that case and note which subsystem owners you would ask.",
        "Day 3: ask the plant one what-if on a measurement you watch and read the caveats.",
        "Day 4: read 'Who decides what': which actions agents do alone and which need you.",
        "Day 5: review this guide with your supervisor and correct anything that is wrong.",
    ]
    summary = (f"{p['role']} ({p['persona_id']}). {p['description']} "
               + (f"Supervisor: {p['supervisor']}." if p["supervisor"] else "No supervisor in the demo roster.")
               + (" External party (simulated)." if p["external"] else ""))
    return OnboardingBriefBody(role_summary=summary[:2000], how_the_plant_works=parts, what_you_watch=watch,
                               who_you_work_with=colleagues[:6], current_open_items=list(ctx["open_case_ids"]),
                               first_week_checklist=checklist, disclaimer=ONBOARDING_DISCLAIMER)


# ----------------------------------------------------------------------------- generation
def _add_tokens(acc: dict[str, int], usage: dict[str, Any]) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int):
            acc[k] = acc.get(k, 0) + v


def generate_brief(persona_id: str, *, client: Any = None, investigations: Optional[Iterable[Any]] = None,
                   work_requests: Optional[Iterable[Any]] = None, persist: bool = True) -> OnboardingBrief:
    """KeyError (404) for an unknown persona."""
    if persona_id not in _personas():
        raise KeyError(f"unknown persona '{persona_id}'")
    invs = list(investigations) if investigations is not None else get_investigations()
    wrs = list(work_requests) if work_requests is not None else get_work_requests()
    ctx = build_context(persona_id, invs, wrs)
    allowed = {i.case_id for i in invs}

    errors_seen: list[str] = []
    meta_calls, latency, tokens = 0, 0, {}
    body: Optional[OnboardingBriefBody] = None
    rewrite_used = False
    fallback_reason: Optional[str] = None
    model_name: Optional[str] = None
    if client is None or not getattr(client, "configured", False):
        fallback_reason = "Meta client not configured"
    else:
        from app.agent.meta_client import MetaClientError

        model_name = getattr(client, "model", None)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": "Structured context (JSON):\n"
                                 + json.dumps(ctx, ensure_ascii=False, default=str)}]
        t0 = time.perf_counter()
        try:
            res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
            meta_calls += 1
            _add_tokens(tokens, res.usage)
            model_name = res.model or model_name
            content = res.message.get("content") or ""
            body, errs = validate_brief(content, allowed)
            if body is None and res.finish_reason == "length":
                errs = ["response truncated (finish_reason=length); return the compact JSON object only"] + errs
            errors_seen += errs
            if body is None:
                rewrite_used = True
                messages += [{"role": "assistant", "content": content},
                             {"role": "user", "content": "Your brief was rejected by the validator. Fix ALL of these "
                              "and return ONLY the corrected JSON object (" + SCHEMA_REMINDER + "):\n"
                              + "\n".join(f"- {e}" for e in errs)}]
                res = client.chat(messages, None, MAX_TOKENS, response_format={"type": "json_object"})
                meta_calls += 1
                _add_tokens(tokens, res.usage)
                body, errs2 = validate_brief(res.message.get("content") or "", allowed)
                errors_seen += [f"rewrite: {e}" for e in errs2]
                if body is None:
                    fallback_reason = "Meta brief rejected after one bounded rewrite"
        except MetaClientError as exc:
            fallback_reason = f"Meta call failed: {str(exc)[:200]}"
            body = None
        latency = int((time.perf_counter() - t0) * 1000)

    if body is not None:
        mode, meta_used = "meta_live", True
        source_label = f"Meta Muse Spark draft ({model_name or config.META_MODEL}), validated"
        body = body.model_copy(update={"disclaimer": ONBOARDING_DISCLAIMER})  # server-owned wording
    else:
        mode, meta_used = "offline_fallback", False
        source_label = OFFLINE_LABEL if meta_calls == 0 else (
            f"deterministic fallback brief — Meta was called {meta_calls}x but its text was rejected and is not used")
        body = fallback_brief(ctx)
        ok, fb_errs = validate_brief(body.model_dump(), allowed)
        if ok is None:  # pragma: no cover - defensive
            log.warning("fallback onboarding brief failed validation: %s", fb_errs)
    brief = OnboardingBrief(
        brief_id=f"ob_{secrets.token_hex(6)}", persona=persona_id, created_at_utc=now_utc(), mode=mode,
        meta_used=meta_used, meta_model=(model_name if meta_calls else None), meta_calls=meta_calls,
        rewrite_used=rewrite_used, fallback_reason=(None if meta_used else fallback_reason),
        validation_errors=[e[:500] for e in errors_seen][:20], source_label=source_label, brief=body,
        latency_ms=(latency if meta_calls else None), tokens=tokens)
    if persist:
        db.save_brief(brief)
    log.info("onboarding %s persona=%s mode=%s meta_calls=%d", brief.brief_id, persona_id, mode, meta_calls)
    return brief
