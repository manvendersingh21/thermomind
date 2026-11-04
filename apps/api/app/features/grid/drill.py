"""Synthetic grid-event drill (S05_GRID_EVENT overlay) + operator-support brief.

The S05 overlay lives in this package (not in app.analytics.scenarios): a sudden synthetic load step of TEY -12 %
over 20 samples, with TIT / GTEP / CDP co-moving by their training-year linear slopes versus TEY. It always works
on a deep COPY of the real window and returns a ScenarioResult-compatible object labelled synthetic=True.

The dataset has no electrical channels (frequency, voltage, reactive power), so the event type only changes the
brief's framing; the data overlay is the same plant-side load-step proxy for every event type, and the brief says so.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import ValidationError

from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.analytics.scenarios import ScenarioResult
from app.features.grid import readiness as rd
from app.features.grid.schemas import (
    BRIEF_DISCLAIMER,
    CoMovement,
    DrillEvent,
    DrillEvidence,
    DrillRequest,
    GridBrief,
    GridDrill,
    GridNumber,
    SeriesPair,
    SeriesPt,
)
from app.schemas import MEASUREMENTS, SampleRange, Transformation

log = logging.getLogger("thermomind.grid.drill")

SCENARIO_ID = "S05_GRID_EVENT"
STEP_FACTOR = 0.88  # TEY -12 %
STEP_ROWS = 20
MIN_DRILL_ROWS = 48
COUPLED = ("TIT", "GTEP", "CDP")
META_MAX_TOKENS = 9000
ALLOWED_VERBS = ("verify", "check", "confirm", "monitor", "communicate", "escalate", "prepare")

EVENT_NOTES = {
    "frequency_dip": ("Synthetic system frequency-dip drill. The public dataset has no frequency channel; the data "
                      "overlay is a plant-side proxy (sudden TEY load step), not a frequency measurement."),
    "overvoltage": ("Synthetic overvoltage drill. The public dataset has no voltage or reactive-power channel; the "
                    "data overlay is a plant-side proxy (sudden TEY load step), not a voltage measurement."),
    "load_step": "Synthetic sudden load-step drill (TEY step) on a copy of real public data.",
}

SYSTEM_PROMPT = (
    "You are ThermoMind's grid-event operator-support agent. Produce a DRAFT operator support brief for a synthetic "
    "drill: what the data shows (cite the numbers given), what the control-room operator should VERIFY per grid code "
    "and site procedures (verb list restricted to verify/check/confirm/monitor/communicate/escalate/prepare), what "
    "the plant can contribute (inertia/voltage support as per the readiness inputs, as capability, not an "
    "instruction), who to notify (TSO/dispatch, shift supervisor, electrical engineer), explicit statement that no "
    "setpoint or control action is issued by this software.\n\n"
    "Output rules: return ONE JSON object only, no prose, with keys headline (string), what_the_data_shows (array "
    "of strings), operator_verifications (array of strings, each starting with one of: verify, check, confirm, "
    "monitor, communicate, escalate, prepare), plant_capability (array of strings), notify (array of strings), "
    "risks (array of strings), disclaimer (string). Never instruct an operator to change a setpoint, operate a "
    "valve or breaker, adjust fuel, trip, shut down, bypass or override anything. The data has no timestamps: refer "
    "to samples only by source year and sample row index, never by calendar date. Label the event as synthetic.\n\n"
    "Budget: all numbers are already computed, so do not re-derive them and keep deliberation brief. Keep the whole "
    "JSON under 1800 characters: headline at most 20 words; at most 4 items per list; each item at most 25 words."
)


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


def coupling_slopes(train: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Training-year linear slope d(col)/d(TEY) and Pearson r for each co-moving channel."""
    tey = pd.to_numeric(train["TEY"], errors="coerce").to_numpy(float)
    out: dict[str, tuple[float, float]] = {}
    for col in COUPLED:
        slope, _, r = rd.linfit(tey, pd.to_numeric(train[col], errors="coerce").to_numpy(float))
        out[col] = (slope or 0.0, r or 0.0)
    return out


def step_rows(n: int) -> tuple[int, int]:
    lo = n // 3
    return lo, min(n, lo + STEP_ROWS)


def apply_grid_event(window: pd.DataFrame, slopes: dict[str, tuple[float, float]], seed: int = 42) -> ScenarioResult:
    """Return a ScenarioResult with a COPY of ``window`` carrying the synthetic S05 load step. Never mutates input."""
    frame = window.copy(deep=True)
    n = len(frame)
    lo, hi = step_rows(n)
    tey = frame["TEY"].to_numpy(dtype=float).copy()
    d_tey = np.zeros(n)
    d_tey[lo:hi] = tey[lo:hi] * (STEP_FACTOR - 1.0)
    frame["TEY"] = tey + d_tey
    transformations = [Transformation(
        measurement="TEY", operation="multiply_step",
        params={"factor": STEP_FACTOR, "rows": [lo, hi], "unit": "MWh"},
        description=f"TEY: multiply by {STEP_FACTOR} (-12%) on window rows [{lo}, {hi}) — synthetic sudden load step")]
    for col in COUPLED:
        slope, r = slopes[col]
        vals = frame[col].to_numpy(dtype=float).copy()
        frame[col] = vals + slope * d_tey
        unit = MEASUREMENTS[col]["unit"]
        transformations.append(Transformation(
            measurement=col, operation="add_coupled_step",
            params={"slope_per_mwh_tey": round(slope, 6), "train_r": round(r, 4), "rows": [lo, hi], "unit": unit},
            description=f"{col}: add {slope:.4f} {unit}/MWh x ΔTEY on rows [{lo}, {hi}) (training-year slope, r={r:.3f})"))
    for col in frame.columns:
        if col in MEASUREMENTS:
            frame[col] = frame[col].astype("float64")
    return ScenarioResult(scenario_id=SCENARIO_ID, synthetic=True, seed=int(seed), frame=frame,
                          transformations=transformations, affected_measurements=["TEY", *COUPLED])


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _m(a: np.ndarray) -> float:
    return float(np.nanmean(a)) if len(a) else float("nan")


def compute_evidence(window: pd.DataFrame, result: ScenarioResult, slopes: dict[str, tuple[float, float]],
                     train: pd.DataFrame, req: DrillRequest, s: int, e: int,
                     capability: dict[str, GridNumber]) -> DrillEvidence:
    n = len(window)
    lo, hi = step_rows(n)
    orig, ov = window, result.frame
    tey_o = orig["TEY"].to_numpy(float)
    tey_v = ov["TEY"].to_numpy(float)
    pre = _m(tey_o[:lo])
    so, sv = _m(tey_o[lo:hi]), _m(tey_v[lo:hi])
    delta = sv - so
    pct = 100.0 * delta / so if so else float("nan")
    co = []
    for col in COUPLED:
        slope, r = slopes[col]
        o, v = orig[col].to_numpy(float), ov[col].to_numpy(float)
        unit = MEASUREMENTS[col]["unit"]
        d = _m(v[lo:hi]) - _m(o[lo:hi])
        co.append(CoMovement(
            measure=col, unit=unit, pre_mean=round(_m(o[:lo]), 3), step_mean_original=round(_m(o[lo:hi]), 3),
            step_mean_overlay=round(_m(v[lo:hi]), 3), delta_overlay_vs_original=round(d, 3),
            train_slope_per_mwh=round(slope, 5), train_r=round(r, 4),
            computation=f"Δ{col} = slope {slope:.4f} x ΔTEY {delta:.2f} = {slope * delta:.3f} {unit} (step mean)"))
    missing = {c: int(window[c].isna().sum()) for c in ["TEY", *COUPLED]}
    oor: dict[str, int] = {}
    for c in ["TEY", *COUPLED]:
        t = pd.to_numeric(train[c], errors="coerce")
        lo_r, hi_r = float(t.min()), float(t.max())
        vv = ov[c].to_numpy(float)
        oor[c] = int(np.sum((vv < lo_r) | (vv > hi_r)))
    dq = "pass" if not any(missing.values()) and not any(oor.values()) else "warn"
    return DrillEvidence(
        event=req.event, event_note=EVENT_NOTES[req.event],
        window=SampleRange(source_year=req.year, start=s, end=e), step_rows=[lo, hi],
        step_samples=SampleRange(source_year=req.year, start=s + lo, end=s + hi),
        tey_pre_mean=round(pre, 3), tey_step_mean_original=round(so, 3), tey_step_mean_overlay=round(sv, 3),
        tey_step_delta=round(delta, 3), tey_step_delta_pct=round(pct, 2),
        tey_computation=(f"step mean TEY overlay {sv:.2f} - original {so:.2f} = {delta:.2f} MWh ({pct:.1f}%) on "
                         f"{req.year} samples #{s + lo}-#{s + hi - 1}; pre-step mean {pre:.2f} MWh"),
        co_movement=co,
        data_quality={"status": dq, "rows": n, "missing": missing, "overlay_out_of_training_range": oor,
                      "note": "TEY is MWh per hourly sample (as published); no timestamps; overlay is synthetic."},
        capability=capability, transformations=result.transformations,
        provenance={"window": "real_observation (UCI 551, copy)", "overlay": "synthetic_overlay (S05_GRID_EVENT)",
                    "co_movement_slopes": "model_derived (training-year OLS)",
                    "capability": "assumption (nameplate, H, pf user inputs)"},
    )


# ---------------------------------------------------------------------------
# Brief: offline fallback, validation, Meta call
# ---------------------------------------------------------------------------


def offline_brief(ev: DrillEvidence) -> GridBrief:
    yr, a, b = ev.window.source_year, ev.step_samples.start, ev.step_samples.end - 1
    cap = ev.capability
    ke, q = cap.get("kinetic_energy_mws"), cap.get("q_headroom_proxy_mvar")
    co_txt = "; ".join(f"{c.measure} {c.delta_overlay_vs_original:+.2f} {c.unit.split(' ')[0]} (training r={c.train_r:.2f})"
                       for c in ev.co_movement)
    event_word = {"frequency_dip": "frequency-dip", "overvoltage": "overvoltage", "load_step": "load-step"}[ev.event]
    return GridBrief(
        headline=(f"[OFFLINE DETERMINISTIC] Synthetic {event_word} drill: TEY step {ev.tey_step_delta:+.1f} MWh "
                  f"({ev.tey_step_delta_pct:+.1f}%) on {yr} samples #{a}-#{b}"),
        what_the_data_shows=[
            f"Synthetic overlay: step-window mean TEY {ev.tey_step_mean_overlay:.2f} MWh vs original "
            f"{ev.tey_step_mean_original:.2f} MWh ({ev.tey_step_delta_pct:+.1f}%); pre-step mean {ev.tey_pre_mean:.2f} MWh.",
            f"Co-movement scaled from training-year slopes: {co_txt}.",
            f"Data quality: {ev.data_quality['status']} (missing {sum(ev.data_quality['missing'].values())}, "
            f"overlay samples outside training range {sum(ev.data_quality['overlay_out_of_training_range'].values())}).",
            ev.event_note,
        ],
        operator_verifications=[
            "Verify the event classification and required response against the grid code and site procedures.",
            "Check unit output, TIT, exhaust pressure and compressor discharge pressure trends on the plant DCS display.",
            "Confirm with dispatch/TSO whether any instruction applies to this unit.",
            "Monitor TIT against the historical envelope shown on the readiness panel.",
            "Communicate the observed step and its sample range to the shift supervisor.",
            "Escalate to the electrical engineer if voltage or reactive-power behaviour is reported by the TSO.",
            "Prepare the event log entry and the data the TSO may request.",
        ],
        plant_capability=[
            (f"Inertia capability (assumption): stored kinetic energy {ke.value:.0f} MW·s ({ke.computation})."
             if ke and ke.value is not None else "Inertia capability: not computed."),
            (f"Reactive capability proxy (assumption): about {q.value:.0f} Mvar circle headroom at current output; "
             f"must be confirmed against the OEM capability curve." if q and q.value is not None
             else "Reactive capability proxy: not computed."),
            "These are capabilities for situational awareness, not instructions.",
        ],
        notify=["TSO / dispatch (per agreed communication channel)", "Shift supervisor", "Electrical engineer"],
        risks=[
            "The overlay is synthetic; real event dynamics (seconds) are far faster than hourly samples.",
            "The dataset has no frequency, voltage or reactive-power channel; electrical behaviour is not observed.",
            "Nameplate, inertia constant and power factor are assumptions, not plant data.",
        ],
        disclaimer=BRIEF_DISCLAIMER,
    )


def _brief_texts(brief: GridBrief) -> list[tuple[str, str]]:
    out = [("headline", brief.headline)]
    for f in ("what_the_data_shows", "operator_verifications", "plant_capability", "notify", "risks"):
        out += [(f"{f}[{i}]", s) for i, s in enumerate(getattr(brief, f))]
    return out


def scan_text(text: str) -> list[str]:
    """Labels of unsafe-instruction patterns found in ``text`` (shared with the contingency tests)."""
    return [label for label, pat in UNSAFE_PATTERNS if pat.search(text or "")]


def validate_brief(raw: Any) -> tuple[Optional[GridBrief], list[str]]:
    data = raw if isinstance(raw, dict) else extract_json(raw) if raw else None
    if data is None:
        return None, ["response is not a JSON object (expected the brief JSON object only, no prose)"]
    data = dict(data)
    model_disclaimer = str(data.get("disclaimer") or "")
    data["disclaimer"] = BRIEF_DISCLAIMER  # fixed text; not the model's to choose
    try:
        brief = GridBrief.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errors: list[str] = []
    for i, item in enumerate(brief.operator_verifications):
        first = re.sub(r"[^a-z]", "", (item.split() or [""])[0].lower())
        if first not in ALLOWED_VERBS:
            errors.append(f"operator_verifications[{i}] must start with one of {list(ALLOWED_VERBS)}; got '{first}'")
    if not any(re.search(r"\d", s) for s in brief.what_the_data_shows):
        errors.append("what_the_data_shows must cite at least one of the numbers given")
    if model_disclaimer and not re.search(r"\bno\b|\bnot\b", model_disclaimer, re.IGNORECASE):
        errors.append("disclaimer must state that no setpoint or control action is issued by this software")
    for where, text in _brief_texts(brief):
        hits = scan_text(text)
        if hits:
            errors.append(f"unsafe_instruction: '{hits[0]}' pattern found in {where}: control actions are forbidden; "
                          f"rephrase as a verification or remove")
        for pat in DATE_PATTERNS:
            m = pat.search(text or "")
            if m:
                errors.append(f"fabricated_date: '{m.group(0)}' in {where}: no timestamps; use source year + sample index")
                break
    return (brief if not errors else None), errors


def _prompt_payload(ev: DrillEvidence) -> dict[str, Any]:
    return {
        "drill": {"synthetic": True, "scenario_id": ev.scenario_id, "event": ev.event, "event_note": ev.event_note},
        "window": ev.window.model_dump(), "step_samples": ev.step_samples.model_dump(),
        "tey": {"unit": "MWh per hourly sample (as published)", "pre_step_mean": ev.tey_pre_mean,
                "step_mean_original": ev.tey_step_mean_original, "step_mean_overlay": ev.tey_step_mean_overlay,
                "step_delta": ev.tey_step_delta, "step_delta_pct": ev.tey_step_delta_pct},
        "co_movement": [c.model_dump(exclude={"computation"}) for c in ev.co_movement],
        "data_quality": ev.data_quality,
        "plant_capability_inputs": {k: {"value": v.value, "unit": v.unit, "provenance": v.provenance,
                                        "computation": v.computation} for k, v in ev.capability.items()},
        "allowed_verification_verbs": list(ALLOWED_VERBS),
        "notify_roles": ["TSO/dispatch", "shift supervisor", "electrical engineer"],
    }


def _tokens(usage: dict) -> Optional[dict[str, int]]:
    return {k: int(v) for k, v in usage.items() if isinstance(v, int)} or None


def meta_brief(client: Any, ev: DrillEvidence, events: list[DrillEvent]) -> tuple[Optional[GridBrief], list[str], Optional[str]]:
    """ONE Muse Spark call + at most one rewrite. Returns (brief|None, validation errors, model id)."""
    from app.agent.meta_client import MetaClientError

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": "Drill evidence (JSON):\n" + json.dumps(_prompt_payload(ev))}]
    errors: list[str] = []
    model: Optional[str] = None
    for attempt in (1, 2):
        events.append(DrillEvent(seq=len(events) + 1, kind="model_request",
                                 summary=f"Muse Spark call {attempt} (max_tokens {META_MAX_TOKENS}, json_object)"))
        try:
            res = client.chat(messages, tools=None, max_tokens=META_MAX_TOKENS,
                              response_format={"type": "json_object"})
        except MetaClientError as exc:
            events.append(DrillEvent(seq=len(events) + 1, kind="error", ok=False, summary=str(exc)[:300]))
            errors.append(f"meta_error: {str(exc)[:200]}")
            return None, errors, model
        model = res.model or model
        content = res.message.get("content")
        events.append(DrillEvent(seq=len(events) + 1, kind="model_response", latency_ms=res.latency_ms,
                                 tokens=_tokens(res.usage),
                                 summary=f"finish_reason={res.finish_reason}; content {len(content or '')} chars"))
        brief, errs = validate_brief(content)
        events.append(DrillEvent(seq=len(events) + 1, kind="validation", ok=brief is not None,
                                 summary="brief valid" if brief else "; ".join(errs)[:400]))
        if brief is not None:
            return brief, errors, model
        errors.extend(f"attempt {attempt}: {e}" for e in errs)
        if attempt == 1:
            events.append(DrillEvent(seq=len(events) + 1, kind="rewrite_requested", summary="one rewrite requested"))
            truncated = res.finish_reason == "length"
            fix = ("Your previous response was empty or cut off by the token limit. Answer now, directly, with a SHORT "
                   "JSON object (at most 3 items per list, each under 20 words)." if truncated else
                   "Return the corrected JSON object only.")
            messages = messages + [
                {"role": "assistant", "content": content or ""},
                {"role": "user", "content": "Your brief failed validation:\n- " + "\n- ".join(errs) + "\n" + fix},
            ]
    return None, errors, model


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grid_drills (
    drill_id   TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    event      TEXT NOT NULL,
    mode       TEXT NOT NULL,
    json       TEXT NOT NULL
)
"""


class DrillStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def save(self, drill: GridDrill) -> GridDrill:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO grid_drills (drill_id, created_at, event, mode, json) VALUES (?,?,?,?,?)",
                         (drill.drill_id, drill.created_at_utc, drill.request.event, drill.mode, drill.model_dump_json()))
        return drill

    def get(self, drill_id: str) -> GridDrill:
        with self._connect() as conn:
            row = conn.execute("SELECT json FROM grid_drills WHERE drill_id = ?", (drill_id,)).fetchone()
        if row is None:
            raise KeyError(f"drill '{drill_id}' not found")
        return GridDrill.model_validate_json(row[0])

    def list(self, limit: int = 50) -> list[GridDrill]:
        with self._connect() as conn:
            rows = conn.execute("SELECT json FROM grid_drills ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                (int(limit),)).fetchall()
        return [GridDrill.model_validate_json(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _series(window: pd.DataFrame, overlay: pd.DataFrame, s: int) -> list[SeriesPair]:
    out = []
    for col in ["TEY", *COUPLED]:
        o = [SeriesPt(row_index=s + i, value=round(float(v), 4)) for i, v in enumerate(window[col].to_numpy(float))]
        v = [SeriesPt(row_index=s + i, value=round(float(x), 4)) for i, x in enumerate(overlay[col].to_numpy(float))]
        out.append(SeriesPair(measure=col, unit=MEASUREMENTS[col]["unit"], original=o, overlay=v))
    return out


def run_drill(bundle, req: DrillRequest, client: Any = None, now_utc: str = "",
              store: Optional[DrillStore] = None) -> GridDrill:
    """Apply S05 to a copy of the window, compute evidence, produce a brief (Meta or offline), persist."""
    window, s, e = rd.resolve_window(bundle, req.year, req.start, req.end, min_rows=MIN_DRILL_ROWS)
    train, _, _ = rd.training_frame(bundle.frame)
    slopes = coupling_slopes(train)
    result = apply_grid_event(window, slopes, req.seed)
    readiness = rd.compute_readiness(bundle, req.year, s, e, req.nameplate_mw, req.h_constant_s, req.power_factor)
    capability = {k: readiness.numbers[k] for k in ("apparent_power_mva", "kinetic_energy_mws", "q_rated_mvar",
                                                     "q_headroom_proxy_mvar", "tit_margin_to_p99")
                  if k in readiness.numbers}
    ev = compute_evidence(window, result, slopes, train, req, s, e, capability)
    events = [
        DrillEvent(seq=1, kind="overlay_applied",
                   summary=f"S05_GRID_EVENT synthetic TEY -12% on window rows {ev.step_rows} (copy; original untouched)"),
        DrillEvent(seq=2, kind="evidence_computed",
                   summary=f"TEY step {ev.tey_step_delta:+.2f} MWh ({ev.tey_step_delta_pct:+.1f}%); data quality "
                           f"{ev.data_quality['status']}"),
    ]
    brief: Optional[GridBrief] = None
    errors: list[str] = []
    model: Optional[str] = None
    meta_attempted = bool(req.use_meta and client is not None and getattr(client, "configured", False))
    if meta_attempted:
        brief, errors, model = meta_brief(client, ev, events)
    elif req.use_meta:
        errors.append("meta requested but no configured Meta client; offline deterministic brief used")
    if brief is not None:
        mode, source, meta_used = "meta_live", "meta", True
        events.append(DrillEvent(seq=len(events) + 1, kind="brief_accepted", summary="Muse Spark brief validated"))
    else:
        brief = offline_brief(ev)
        mode = "offline_fallback" if req.use_meta else "offline_preview"
        source, meta_used = "deterministic_offline", False
        if req.use_meta:
            events.append(DrillEvent(seq=len(events) + 1, kind="fallback", ok=False,
                                     summary="offline deterministic brief used (labelled)"))
    drill = GridDrill(
        drill_id=f"drill_{secrets.token_hex(6)}", created_at_utc=now_utc, request=req, mode=mode,
        meta_used=meta_used, meta_model=model if meta_used else None, brief=brief, brief_source=source,
        evidence=ev, series=_series(window, result.frame, s), validation_errors=errors, events=events,
    )
    if store is not None:
        store.save(drill)
    return drill
