"""Watchdog agent: detectors with explicit rules + provenance → proposals → deliberation → policy routing.

Detectors (each documented in docs/WATCHDOG.md; thresholds are module constants):

R1  auxiliary_overheating — "burning out" signature on a RUNNING auxiliary motor (running ≥ 60 s):
      slope    = least-squares dθ/dt of the winding temperature over the last 120 s
      θ_ss_est = θ + τ·slope                    (first-order model, τ from the motor datasheet assumption)
      t_alarm, t_limit = τ·ln((θ_ss_est − θ)/(θ_ss_est − θ_target))   (None if θ_ss_est ≤ target)
      excess   = I_measured / I_expected − 1    (I_expected = healthy model at the present demand)
    fires if θ ≥ alarm, OR (θ_ss_est ≥ limit AND slope ≥ 0.2 K/min AND (excess ≥ 5 % OR vibration zone C/D OR
    insulation resistance < (kV + 1) MΩ)).
    severity: critical if θ ≥ limit − 5 K or t_limit ≤ 10 min; high if θ ≥ alarm or t_limit ≤ 30 min; else warning.
R1b auxiliary_underload — running fan drawing < 85 % of the expected current for ≥ 60 s (belt slip / decoupling).
R2  capability_shortfall — "need more power": dispatch setpoint > available output (min of the auxiliary-limited
    capability and the thermal-limited capability of the electrical balance of plant at the present ambient,
    reusing app.features.thermal) by > 1 MWh per hourly sample for ≥ 30 simulated s.
R3  baseline_deviation — replayed REAL UCI row: |mean(TEY − baseline expectation) over the last 6 rows| >
    3·σ_val/√6 (σ_val = validation residual std of the production baseline), or any measurement outside the
    model's training range.

Every Detection carries evidence numbers + provenance and a proposed action INTENT. Nothing in this module reaches
any real plant: the only execution path is ``AuxiliariesModel.request_switchover`` on the in-memory simulation.
"""
from __future__ import annotations

import itertools
import logging
import math
import secrets
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np

from app.features.watchdog import deliberation as delib
from app.features.watchdog import policy as pol
from app.features.watchdog.auxiliaries import (
    SIMULATED_LABEL,
    UNIT_RATED_MWH,
    AuxiliariesModel,
    InterlockError,
    Motor,
    time_to_reach_s,
    vibration_zone,
)

log = logging.getLogger("thermomind.watchdog")

# ---- rule constants (documented) -----------------------------------------------------------------------------
SLOPE_WINDOW_S = 120
MIN_RUNNING_S = 60.0
SLOPE_MIN_K_PER_MIN = 0.2
CURRENT_EXCESS_MIN = 0.05
UNDERLOAD_RATIO = 0.85
UNDERLOAD_PERSIST_S = 60.0
SHORTFALL_MIN_MWH = 1.0
SHORTFALL_PERSIST_S = 30.0
RESIDUAL_ROWS = 6
RESIDUAL_K_SIGMA = 3.0
DETECT_EVERY_S = 5
REARM_AFTER_S = 120.0
SECONDS_PER_UCI_ROW = 3600.0
MAX_SPEED = 600.0
MAX_STEPS_PER_TICK = 2000
BUF = {"events": 500, "detections": 200, "proposals": 200, "executions": 200, "human_tasks": 200, "outbox": 300}
INSPECTION = {"bearing": "bearing inspection", "insulation": "insulation resistance / PI testing",
              "unknown": "inspection"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def slope_per_s(ts: np.ndarray, ys: np.ndarray) -> float:
    if ts.size < 2:
        return 0.0
    tc = ts - ts.mean()
    den = float((tc * tc).sum())
    return float((tc * (ys - ys.mean())).sum() / den) if den > 0 else 0.0


# =============================================================================================== detectors (pure)
def evaluate_overheat(m: Motor, expected_current_a: float, t_s: float) -> Optional[dict[str, Any]]:
    """Rule R1 on one motor. Returns the evidence dict when the rule fires, else None."""
    spec = m.spec
    if m.state != "running" or (t_s - m.state_since_s) < MIN_RUNNING_S:
        return None
    hist = [h for h in itertools.islice(reversed(m.history), SLOPE_WINDOW_S) if h[0] > t_s - SLOPE_WINDOW_S]
    if len(hist) < 10:
        return None
    ts = np.array([h[0] for h in hist], dtype=float)
    th = np.array([h[1] for h in hist], dtype=float)
    theta = float(th[0])  # hist is newest-first
    slope = slope_per_s(ts, th)
    theta_ss_est = theta + spec.tau_s * slope
    t_alarm = time_to_reach_s(theta, theta_ss_est, spec.alarm_c, spec.tau_s)
    t_limit = time_to_reach_s(theta, theta_ss_est, spec.limit_c, spec.tau_s)
    lin_t_limit = (spec.limit_c - theta) / slope if slope > 1e-9 and theta < spec.limit_c else None
    excess = (m.current_a / expected_current_a - 1.0) if expected_current_a > 0 else 0.0
    zone = vibration_zone(m.vibration_mm_s)
    ir_min = spec.voltage_v / 1000.0 + 1.0
    ir_low = m.insulation_mohm < ir_min
    supporting = excess >= CURRENT_EXCESS_MIN or zone in ("C", "D") or ir_low
    fires = theta >= spec.alarm_c or (theta_ss_est >= spec.limit_c and slope * 60.0 >= SLOPE_MIN_K_PER_MIN
                                       and supporting)
    if not fires:
        return None
    ttl_cons = min([x for x in (t_limit, lin_t_limit) if x is not None], default=None)
    if theta >= spec.limit_c - 5.0 or (ttl_cons is not None and ttl_cons <= 600):
        severity = "critical"
    elif theta >= spec.alarm_c or (ttl_cons is not None and ttl_cons <= 1800):
        severity = "high"
    else:
        severity = "warning"
    signature = "insulation" if ir_low else ("bearing" if zone in ("C", "D") or excess >= CURRENT_EXCESS_MIN else "unknown")
    return {
        "severity": severity, "signature": signature,
        "numbers": {
            "winding_c": round(theta, 2), "alarm_c": spec.alarm_c, "limit_c": spec.limit_c,
            "margin_to_alarm_k": round(spec.alarm_c - theta, 2), "margin_to_limit_k": round(spec.limit_c - theta, 2),
            "slope_k_per_min": round(slope * 60.0, 3), "tau_s": spec.tau_s,
            "theta_ss_est_c": round(theta_ss_est, 1),
            "time_to_alarm_s": None if t_alarm is None else round(t_alarm, 0),
            "time_to_limit_s": None if t_limit is None else round(t_limit, 0),
            "time_to_limit_linear_s": None if lin_t_limit is None else round(lin_t_limit, 0),
            "time_to_limit_conservative_s": None if ttl_cons is None else round(ttl_cons, 0),
            "current_a": round(m.current_a, 2), "expected_current_a": round(expected_current_a, 2),
            "current_excess_pct": round(100.0 * excess, 2),
            "vibration_mm_s": round(m.vibration_mm_s, 2), "vibration_zone": zone,
            "bearing_c": round(m.bearing_c, 1), "insulation_mohm": round(m.insulation_mohm, 1),
            "insulation_min_mohm": round(ir_min, 1),
        },
        "provenance": [
            f"SIMULATED measurements from the {SIMULATED_LABEL} ({spec.asset_id}); window last {SLOPE_WINDOW_S} s",
            "slope: least-squares fit of winding temperature vs simulated time",
            "θ_ss_est = θ + τ·slope (first-order winding model; τ is a datasheet ASSUMPTION)",
            "time-to-limit = τ·ln((θ_ss_est − θ)/(θ_ss_est − limit)) and linear (limit − θ)/slope; severity uses the "
            "smaller (conservative) of the two",
            "I_expected: healthy electrical model at the present duty demand",
            "limits: alarm 130 °C / limit 155 °C = typical class-F settings (IEC 60034-1, IEC 60085, NEMA MG-1) — "
            "not plant-specific",
            "vibration zones: ISO 20816-3 group-2 rigid typical boundaries 1.4/2.8/4.5 mm/s",
            "insulation minimum: IEEE Std 43 (kV + 1) MΩ",
        ],
    }


def evaluate_underload(m: Motor, expected_current_a: float, t_s: float, since: Optional[float]) -> bool:
    if m.state != "running" or m.spec.load_law != "fan" or (t_s - m.state_since_s) < MIN_RUNNING_S:
        return False
    return expected_current_a > 0 and m.current_a / expected_current_a < UNDERLOAD_RATIO


def thermal_limited_capability(ambient_c: float) -> dict[str, Any]:
    """Max load ratio keeping every electrical BoP asset below its ALARM (thermal feature models, defaults)."""
    try:
        from app.features.thermal import model as tm
        from app.features.thermal.schemas import ThermalAssumptions
    except Exception:  # noqa: BLE001 - optional reuse
        return {"available": False, "mwh": None, "binding": None, "provenance": "thermal feature not importable"}
    a = ThermalAssumptions()
    amb_in = ambient_c + a.indoor_ambient_offset_k
    cands = {}

    def k_quad(alarm: float, rise: float) -> float:
        return math.sqrt(max(0.0, alarm - amb_in) / rise) if rise > 0 else float("inf")
    cands["GEN"] = k_quad(a.generator_alarm_c, a.generator_rated_rise_k) * a.generator_rated_mwh
    cands["GCB"] = k_quad(a.contact_alarm_c, a.contact_rated_rise_k) * a.generator_rated_mwh
    cands["HVSG"] = k_quad(a.contact_alarm_c, a.contact_rated_rise_k) * a.hv_rated_mwh
    cands["BUS"] = k_quad(a.busbar_alarm_c, a.busbar_rated_rise_k) * a.hv_rated_mwh
    lo, hi = 0.0, 2.0  # transformer hot spot (IEEE C57.91 steady state) via bisection on K
    for _ in range(40):
        mid = (lo + hi) / 2
        _, hs = tm.transformer_steady_state(mid, ambient_c, top_oil_rise_rated=a.top_oil_rise_rated_k,
                                            hot_spot_gradient_rated=a.hot_spot_gradient_rated_k, r=a.loss_ratio_r,
                                            n=a.exponent_n, m=a.exponent_m)
        lo, hi = (mid, hi) if hs < a.transformer_hot_spot_alarm_c else (lo, mid)
    cands["GSU"] = lo * a.transformer_rated_mwh
    binding = min(cands, key=cands.get)
    return {"available": True, "mwh": round(min(cands.values()), 2), "binding": binding,
            "per_asset_mwh": {k: round(v, 1) for k, v in cands.items()},
            "provenance": "app.features.thermal model (IEEE C57.91 / I²R quasi-steady state), default assumptions, "
                          f"ambient {ambient_c:.1f} °C, alarm-level limits"}


# =============================================================================================== demand source
class DemandSource:
    """Simulator (guarded) → replayed UCI load through the simulated historian → fixed nominal profile."""

    def __init__(self, mode: str = "auto", year: int = 2014, start_index: int = 1200,
                 frame_provider: Optional[Callable[[int], Any]] = None):
        self.mode_requested = mode
        self.year = int(year)
        self.start_index = int(start_index)
        self.kind = "nominal"
        self.label = "fixed nominal profile (no data source available)"
        self.historian = None
        self.row: dict[str, Any] = {}
        self.new_row = False
        self._frame_provider = frame_provider
        self._next_row_at = SECONDS_PER_UCI_ROW
        self._sim_cache: Optional[dict] = None
        self._open()

    def _open(self) -> None:
        if self.mode_requested in ("auto", "simulator") and simulator_reading() is not None:
            self.kind, self.label = "simulator", "app.simulator running engine (SIMULATED plant state)"
            return
        if self.mode_requested in ("auto", "replay"):
            try:
                from app.connectors.simulated_historian import SimulatedHistorian
                provider = self._frame_provider or _uci_year_frame
                self.historian = SimulatedHistorian(provider)
                self.historian.start(self.year, advance_rate=0.0, start_index=self.start_index)
                self.kind = "uci_replay"
                self.label = (f"replayed REAL UCI rows (source_year {self.year}) via the simulated historian; one row "
                              f"= one hourly aggregate held for {SECONDS_PER_UCI_ROW:.0f} simulated s; no timestamps")
                self._load_row()
                return
            except Exception as exc:  # noqa: BLE001
                log.info("replay source unavailable: %s", type(exc).__name__)
                self.historian = None
        self.kind = "nominal"
        self.row = {"TEY": 0.74 * UNIT_RATED_MWH, "AT": 15.0}

    def _load_row(self) -> None:
        latest = self.historian.latest(1)
        rows = latest.get("rows") or []
        if rows:
            self.row = rows[-1]
            self.new_row = True

    def advance(self, t_s: float) -> None:
        if self.kind == "uci_replay" and t_s >= self._next_row_at:
            self._next_row_at += SECONDS_PER_UCI_ROW
            try:
                self.historian.tick(1)
                self._load_row()
            except Exception:  # noqa: BLE001
                pass
        elif self.kind == "simulator" and int(t_s) % DETECT_EVERY_S == 0:
            self._sim_cache = simulator_reading()

    def reading(self) -> dict[str, Any]:
        if self.kind == "simulator":
            r = self._sim_cache or simulator_reading() or {}
            return {"output_mwh": r.get("output_mwh"), "ambient_c": r.get("ambient_c"),
                    "cooling_frac": r.get("cooling_frac"), "feedwater_frac": r.get("feedwater_frac"),
                    "dispatch_mwh": r.get("dispatch_mwh")}
        return {"output_mwh": self.row.get("TEY"), "ambient_c": self.row.get("AT"), "cooling_frac": None,
                "feedwater_frac": None, "dispatch_mwh": None}

    def describe(self) -> dict[str, Any]:
        out = {"kind": self.kind, "label": self.label}
        if self.kind == "uci_replay" and self.historian is not None:
            c = self.historian.cursor()
            out.update({"source_year": c.get("source_year"), "row_index": self.row.get("row_index"),
                        "replay_tick": c.get("replay_tick"), "time_axis": c.get("time_axis"),
                        "TEY_mwh": self.row.get("TEY"), "AT_c": self.row.get("AT")})
        return out


def _uci_year_frame(year: int):
    from app import services
    try:
        bundle = services.get_repo().get(services.UCI_DATASET_ID)
    except KeyError:
        services.seed_uci_if_available()
        bundle = services.get_repo().get(services.UCI_DATASET_ID)
    return bundle.year_frame(int(year))


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def simulator_reading() -> Optional[dict[str, Any]]:
    """Best-effort, guarded read of a RUNNING ``app.simulator`` engine. None when absent or not running."""
    try:
        import importlib
        sim = importlib.import_module("app.simulator")
    except Exception:  # noqa: BLE001
        return None
    eng = None
    for name in ("get_engine", "get_simulator", "engine", "ENGINE", "simulator"):
        obj = getattr(sim, name, None)
        if obj is None:
            continue
        try:
            eng = obj() if callable(obj) and not hasattr(obj, "running") else obj
        except Exception:  # noqa: BLE001
            eng = None
        if eng is not None:
            break
    if eng is None or not bool(getattr(eng, "running", False)):
        return None
    state = None
    for meth in ("state", "snapshot", "get_state", "latest"):
        f = getattr(eng, meth, None)
        if callable(f):
            try:
                state = f()
                break
            except Exception:  # noqa: BLE001
                continue
    if hasattr(state, "model_dump"):
        state = state.model_dump()
    if not isinstance(state, dict):
        return None
    flat: dict[str, Any] = {}

    def walk(d: Any, prefix: str = "") -> None:
        if isinstance(d, dict):
            for k, v in d.items():
                walk(v, f"{prefix}{k}.".lower())
        else:
            flat[prefix.rstrip(".")] = d

    walk(state)

    def pick(*must: str) -> Optional[float]:
        for k, v in flat.items():
            if all(m in k for m in must):
                f = _num(v)
                if f is not None:
                    return f
        return None
    out = pick("output") or pick("power") or pick("tey")
    disp = pick("dispatch") or pick("setpoint")
    cond = pick("condenser", "heat") or pick("condenser", "duty")
    steam = pick("steam", "flow")
    cond_r = pick("condenser", "rated")
    steam_r = pick("steam", "rated")
    return {"output_mwh": out, "dispatch_mwh": disp, "ambient_c": pick("ambient") or pick("at"),
            "cooling_frac": (cond / cond_r) if cond and cond_r else (out / UNIT_RATED_MWH if out else None),
            "feedwater_frac": (steam / steam_r) if steam and steam_r else (out / UNIT_RATED_MWH if out else None)}


# =============================================================================================== watchdog
class Watchdog:
    def __init__(self, *, source: str = "auto", year: int = 2014, start_index: int = 1200, seed: int = 7,
                 meta_client: Any = None, deliberation_backend: str = "auto", sync_deliberation: bool = False,
                 persist_notifications: bool = True, frame_provider: Optional[Callable[[int], Any]] = None):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="watchdog-delib")
        self.meta_client = meta_client
        self.deliberation_backend = deliberation_backend
        self.sync_deliberation = sync_deliberation
        self.persist_notifications = persist_notifications
        self.policy = pol.PolicyConfig()
        self._frame_provider = frame_provider
        self.speed = 60.0
        self._init_sim(source, year, start_index, seed)

    # ------------------------------------------------------------------ lifecycle
    def _init_sim(self, source: str, year: int, start_index: int, seed: int) -> None:
        self.seed = seed
        self.source_mode, self.year, self.start_index = source, year, start_index
        self.source = DemandSource(source, year, start_index, self._frame_provider)
        r = self.source.reading()
        amb = _num(r.get("ambient_c"))
        self.aux = AuxiliariesModel(ambient_c=amb if amb is not None else 15.0, seed=seed)
        self.demand_step_mwh = 0.0
        self.seq = 0
        self.events: deque = deque(maxlen=BUF["events"])
        self.detections: deque = deque(maxlen=BUF["detections"])
        self.proposals: deque = deque(maxlen=BUF["proposals"])
        self.executions: deque = deque(maxlen=BUF["executions"])
        self.human_tasks: deque = deque(maxlen=BUF["human_tasks"])
        self.outbox: deque = deque(maxlen=BUF["outbox"])
        self._active: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending_since: dict[tuple[str, str], float] = {}
        self._residuals: deque = deque(maxlen=24)
        self._exec_by_switchover: dict[str, dict] = {}
        self._last_unit: dict[str, Any] = {}
        self._apply_demand()
        self.aux._settle()

    def start(self, speed: Optional[float] = None) -> None:
        with self._lock:
            if speed is not None:
                self.speed = float(speed)
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="watchdog-sim", daemon=True)
            self._thread.start()
            self._event("control", f"simulation started at {self.speed:g}× (Δt = 1 s simulated)")

    def stop(self, timeout: float = 3.0) -> bool:
        t = self._thread
        self._stop.set()
        if t is not None:
            t.join(timeout)
        with self._lock:
            alive = bool(t is not None and t.is_alive())
            if t is not None:
                self._event("control", "simulation stopped")
            self._thread = None
            return not alive

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def reset(self, source: Optional[str] = None, year: Optional[int] = None, start_index: Optional[int] = None,
              seed: Optional[int] = None) -> None:
        self.stop()
        with self._lock:
            self._init_sim(source or self.source_mode, year if year is not None else self.year,
                           start_index if start_index is not None else self.start_index,
                           seed if seed is not None else self.seed)
            self._event("control", "simulation reset (auxiliaries, detections, proposals and records cleared)")

    def shutdown(self) -> None:
        self.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self) -> None:
        last = time.monotonic()
        carry = 0.0
        while not self._stop.is_set():
            time.sleep(0.05)
            now = time.monotonic()
            carry += (now - last) * self.speed
            last = now
            n = min(int(carry), MAX_STEPS_PER_TICK)
            carry -= int(carry)
            if n:
                try:
                    self.step_n(n)
                except Exception:  # noqa: BLE001 - never kill the loop silently
                    log.exception("watchdog step failed")
                    self._stop.set()

    # ------------------------------------------------------------------ simulation step
    def _apply_demand(self) -> None:
        r = self.source.reading()
        base = _num(r.get("output_mwh"))
        base = base if base is not None else 0.74 * UNIT_RATED_MWH
        disp = _num(r.get("dispatch_mwh"))
        self.dispatch_mwh = (disp if disp is not None else base) + self.demand_step_mwh
        unit = self.aux.unit_capability()
        th = thermal_limited_capability(self.aux.ambient_c) if self._need_thermal() else self._last_thermal
        self._last_thermal = th
        avail = min(unit["aux_limited_mwh"], th["mwh"] if th.get("mwh") is not None else float("inf"),
                    UNIT_RATED_MWH)
        self.output_mwh = min(self.dispatch_mwh, avail)
        d = self.output_mwh / UNIT_RATED_MWH
        cool = _num(r.get("cooling_frac"))
        fw = _num(r.get("feedwater_frac"))
        self.aux.set_demand(cool if cool is not None else d, fw if fw is not None else d, _num(r.get("ambient_c")))
        self._last_unit = {**unit, "thermal_limited_mwh": th.get("mwh"), "thermal_binding": th.get("binding"),
                           "available_mwh": round(avail, 2), "dispatch_setpoint_mwh": round(self.dispatch_mwh, 2),
                           "output_mwh": round(self.output_mwh, 2), "demand_step_mwh": self.demand_step_mwh,
                           "shortfall_mwh": round(max(0.0, self.dispatch_mwh - avail), 2),
                           "unit_of_measure": "MWh per hourly sample (TEY unit, as published)"}

    _last_thermal: dict = {}
    _thermal_amb: Optional[float] = None

    def _need_thermal(self) -> bool:
        amb = round(self.aux.ambient_c, 1)
        if self._thermal_amb != amb or not self._last_thermal:
            self._thermal_amb = amb
            return True
        return False

    def step_n(self, n: int) -> None:
        for _ in range(int(n)):
            with self._lock:
                self.source.advance(self.aux.t_s + 1.0)
                if self.source.new_row:
                    self.source.new_row = False
                    self._on_new_row()
                self._apply_demand()
                res = self.aux.step(1.0)
                for tr in res["trips"]:
                    self._event("trip", f"{tr['asset_id']} tripped by its thermal overload protection (simulated): "
                                        f"{tr['reason']}", asset=tr["asset_id"])
                for sw in res["switchovers"]:
                    self._on_switchover_finished(sw)
                if int(self.aux.t_s) % DETECT_EVERY_S == 0:
                    self._detect()

    # ------------------------------------------------------------------ events / notifications
    def _event(self, etype: str, message: str, **refs: Any) -> dict:
        self.seq += 1
        ev = {"seq": self.seq, "ts_utc": now_utc(), "t_sim_s": round(self.aux.t_s, 1), "type": etype,
              "message": message, **{k: v for k, v in refs.items() if v is not None}}
        self.events.append(ev)
        return ev

    def _notify(self, personas: list[str], message: str, ref: dict[str, Any]) -> list[str]:
        sent = []
        for pid in dict.fromkeys(personas):
            rec = {"id": new_id("wdn"), "ts_utc": now_utc(), "persona": pid, "message": message[:600],
                   "delivery": "in_app_simulated", "channel": "in-memory outbox", **ref}
            if self.persist_notifications:
                try:
                    from app.plant import store
                    from app.plant.schemas import Notification
                    store.save_notification(Notification(
                        id=rec["id"], persona=pid, kind="info", created_at_utc=rec["ts_utc"],
                        message=f"[WATCHDOG · SIMULATED auxiliaries] {message}"[:2000]))
                    rec["channel"] = "plant inbox (simulated in-app)"
                except Exception:  # noqa: BLE001 - guarded; outbox still records it
                    pass
            self.outbox.append(rec)
            sent.append(pid)
        return sent

    # ------------------------------------------------------------------ detectors
    def _on_new_row(self) -> None:
        """R3 on each replayed REAL row."""
        try:
            from app import services
            model = services.get_model()
        except Exception:  # noqa: BLE001
            model = None
        row = self.source.row
        if model is None or not row:
            return
        try:
            import pandas as pd
            frame = pd.DataFrame([{k: row.get(k) for k in model.features}])
            if frame.isna().any(axis=None):
                return
            expected = float(model.predict(frame)[0])
        except Exception:  # noqa: BLE001
            return
        tey = _num(row.get("TEY"))
        if tey is None:
            return
        self._residuals.append(tey - expected)
        ev = model.evaluation
        sigma = float(ev.residual_std_validation)
        ood = {k: row.get(k) for k, (lo, hi) in (ev.feature_ranges_train or {}).items()
               if _num(row.get(k)) is not None and not (lo <= float(row[k]) <= hi)}
        last = list(self._residuals)[-RESIDUAL_ROWS:]
        mean_r = float(np.mean(last)) if last else 0.0
        thr = RESIDUAL_K_SIGMA * sigma / math.sqrt(RESIDUAL_ROWS)
        fires = (len(last) >= RESIDUAL_ROWS and abs(mean_r) > thr) or bool(ood)
        key = ("baseline_deviation", "TEY")
        if not fires:
            self._clear(key)
            return
        if key in self._active:
            self._active[key]["last_true_s"] = self.aux.t_s
            return
        evidence = {"numbers": {"TEY_mwh": tey, "expected_TEY_mwh": round(expected, 2),
                                "mean_residual_last6_mwh": round(mean_r, 3), "threshold_mwh": round(thr, 3),
                                "sigma_validation_mwh": round(sigma, 3), "out_of_training_range": ood,
                                "source_year": row.get("source_year"), "row_index": row.get("row_index")},
                    "provenance": ["REAL UCI row replayed through the simulated historian (no timestamp)",
                                   f"expected TEY: production baseline {getattr(ev, 'model_id', '?')} "
                                   "(services.get_model())",
                                   f"rule: |mean residual of last {RESIDUAL_ROWS} rows| > {RESIDUAL_K_SIGMA:g}·σ_val/√"
                                   f"{RESIDUAL_ROWS}, or a measurement outside feature_ranges_train"]}
        self._open_detection("baseline_deviation", "TEY", "watch", evidence,
                             intent=("open an engineering investigation into TEY departing from the baseline "
                                     "expectation over the last replayed rows"),
                             action_class="investigation_request", magnitude=round(mean_r, 3),
                             responsible=["performance_engineer", "reliability_engineer"],
                             rationale=f"mean residual {mean_r:+.2f} MWh vs threshold ±{thr:.2f} MWh"
                                       + (f"; out of training range: {', '.join(ood)}" if ood else ""))

    def _clear(self, key: tuple[str, str]) -> None:
        act = self._active.get(key)
        if act and self.aux.t_s - act["last_true_s"] >= REARM_AFTER_S:
            del self._active[key]

    def _detect(self) -> None:
        t = self.aux.t_s
        for aid, m in self.aux.motors.items():
            key = ("auxiliary_overheating", aid)
            if m.state == "running":
                exp_i = self.aux.expected_current_a(aid)
                ev = evaluate_overheat(m, exp_i, t)
                if ev is not None:
                    if key in self._active:
                        self._active[key]["last_true_s"] = t
                    else:
                        self._overheat_detection(m, ev)
                else:
                    self._clear(key)
                ukey = ("auxiliary_underload", aid)
                if evaluate_underload(m, exp_i, t, None):
                    since = self._pending_since.setdefault(ukey, t)
                    if t - since >= UNDERLOAD_PERSIST_S and ukey not in self._active:
                        ratio = m.current_a / exp_i
                        self._open_detection(
                            "auxiliary_underload", aid, "warning",
                            {"numbers": {"current_a": round(m.current_a, 2), "expected_current_a": round(exp_i, 2),
                                         "ratio": round(ratio, 3), "threshold": UNDERLOAD_RATIO,
                                         "persisted_s": t - since,
                                         "vibration_mm_s": round(m.vibration_mm_s, 2)},
                             "provenance": [f"SIMULATED {aid} current vs healthy fan model (affinity law P ∝ n³)",
                                            f"rule: I/I_expected < {UNDERLOAD_RATIO} for ≥ {UNDERLOAD_PERSIST_S:.0f} s"]},
                            intent=f"inspect {m.spec.name.lower()} drive belts (suspected belt slip; airflow reduced)",
                            action_class="auxiliary_maintenance", magnitude=round(1 - ratio, 3),
                            responsible=[m.spec.responsible_persona],
                            rationale=f"{aid} draws {100 * ratio:.0f} % of expected current at unchanged demand — "
                                      "consistent with belt slip / partial decoupling (fan power ∝ speed³)")
                    elif ukey in self._active:
                        self._active[ukey]["last_true_s"] = t
                else:
                    self._pending_since.pop(ukey, None)
                    self._clear(ukey)
            else:
                self._clear(key)
        # R2 capability shortfall
        u = self._last_unit
        key = ("capability_shortfall", "UNIT")
        sf = float(u.get("shortfall_mwh") or 0.0)
        if sf > SHORTFALL_MIN_MWH:
            since = self._pending_since.setdefault(key, t)
            if key in self._active:
                self._active[key]["last_true_s"] = t
            elif t - since >= SHORTFALL_PERSIST_S:
                self._shortfall_detection(u, t - since)
        else:
            self._pending_since.pop(key, None)
            self._clear(key)

    def _overheat_detection(self, m: Motor, ev: dict) -> None:
        aid, spec = m.spec.asset_id, m.spec
        peers = [o for o in self.aux.group_members(spec.group) if o is not m]
        n = ev["numbers"]
        what = INSPECTION[ev["signature"]]
        params: dict[str, Any] = {}
        if spec.group in ("cooling_water", "feedwater") and peers and not peers[0].running:
            other = peers[0]
            label = "cooling-water" if spec.group == "cooling_water" else "boiler feedwater"
            intent = (f"SIMULATED switchover: duty moves to standby {label} pump {other.spec.asset_id[-1]}; "
                      f"pump {aid[-1]} released for {what}")
            cls = "simulated_auxiliary_switchover"
            params = {"group": spec.group, "start": other.spec.asset_id, "stop": aid}
            responsible = [spec.responsible_persona if ev["signature"] != "insulation" else "electrical_engineer"]
        else:
            intent = (f"plan {what} of {spec.name.lower()} (no standby available in this group); consider reducing "
                      "its duty through operations")
            cls = "auxiliary_maintenance"
            responsible = [spec.responsible_persona]
        ttl = n.get("time_to_limit_conservative_s")
        ttl_txt = f"{ttl / 60:.1f} min" if ttl is not None else "not reached at the present trend"
        rationale = (f"{aid} winding {n['winding_c']:.1f} °C (alarm {n['alarm_c']:.0f}, limit {n['limit_c']:.0f}), rising "
                     f"{n['slope_k_per_min']:.2f} K/min toward ≈{n['theta_ss_est_c']:.0f} °C; time to limit {ttl_txt}; "
                     f"current {n['current_excess_pct']:+.1f} % vs expected; vibration {n['vibration_mm_s']:.1f} mm/s "
                     f"(zone {n['vibration_zone']}) → {ev['signature']} 'burning out' signature")
        self._open_detection("auxiliary_overheating", aid, ev["severity"], ev, intent=intent, action_class=cls,
                             magnitude=1.0, responsible=responsible, rationale=rationale, params=params)

    def _shortfall_detection(self, u: dict, persisted: float) -> None:
        sf = float(u["shortfall_mwh"])
        disp = float(u["dispatch_setpoint_mwh"])
        frac = sf / disp if disp else 1.0
        severity = "critical" if frac >= 0.10 else ("high" if frac >= 0.03 else "warning")
        aux_note = ""
        if u.get("aux_binding") not in (None, "nameplate"):
            aux_note = (f"; auxiliary-limited ({u['aux_binding']}: CW {u['cw_capacity_frac']:.0%}, feedwater "
                        f"{u['feedwater_capacity_frac']:.0%}, fan airflow {u['fan_airflow_frac']:.0%})")
        intent = (f"human decision needed: second-unit commitment for +{sf:.1f} MWh per hourly sample, or a "
                  f"re-dispatch question to the dispatcher (target {u['available_mwh']:.1f})")
        notify_grid = []
        try:
            from app.features.grid.readiness import NOTIFY
            notify_grid = list(NOTIFY)
        except Exception:  # noqa: BLE001
            pass
        ev = {"numbers": {"dispatch_setpoint_mwh": disp, "available_mwh": u["available_mwh"], "shortfall_mwh": sf,
                          "shortfall_pct": round(100 * frac, 2), "aux_limited_mwh": u["aux_limited_mwh"],
                          "thermal_limited_mwh": u.get("thermal_limited_mwh"),
                          "thermal_binding_asset": u.get("thermal_binding"), "rated_mwh": u["rated_mwh"],
                          "demand_step_mwh": u.get("demand_step_mwh"), "persisted_s": persisted,
                          "cooling_capacity_frac": u["cooling_capacity_frac"]},
              "provenance": [f"dispatch setpoint = {self.source.kind} output proxy + simulated demand step "
                             "(MWh per hourly sample, TEY unit as published)",
                             "aux-limited capability: SIMULATED auxiliaries (steam-cycle share 1/3 ASSUMPTION)",
                             "thermal-limited capability: app.features.thermal models at present ambient (alarm "
                             "limits, default assumptions)",
                             f"rule: dispatch − available > {SHORTFALL_MIN_MWH:g} for ≥ {SHORTFALL_PERSIST_S:.0f} s",
                             *([f"grid feature notify list: {', '.join(notify_grid)}"] if notify_grid else [])]}
        self._open_detection("capability_shortfall", "UNIT", severity, ev, intent=intent,
                             action_class="unit_commitment", magnitude=round(sf, 2),
                             responsible=["electrical_engineer", "plant_manager"],
                             rationale=f"dispatch {disp:.1f} exceeds available {u['available_mwh']:.1f} by {sf:.1f} "
                                       f"({100 * frac:.1f} %){aux_note} → need more power")

    # ------------------------------------------------------------------ pipeline
    def _open_detection(self, kind: str, asset: str, severity: str, evidence: dict, *, intent: str, action_class: str,
                        magnitude: float, responsible: list[str], rationale: str,
                        params: Optional[dict] = None) -> dict:
        det = {"id": new_id("det"), "ts_utc": now_utc(), "t_sim_s": self.aux.t_s, "kind": kind, "asset": asset,
               "severity": severity, "evidence": evidence, "rationale": rationale,
               "proposed_action": {"intent": intent, "action_class": action_class, "magnitude": magnitude,
                                   "params": params or {}},
               "simulated": asset != "TEY", "source": self.source.kind}
        self.detections.append(det)
        self._active[(kind, asset)] = {"detection_id": det["id"], "last_true_s": self.aux.t_s}
        self._event("detection", f"[{severity}] {kind} on {asset}: {rationale}", detection_id=det["id"], asset=asset)
        ac = pol.action_class(action_class)
        prop = {"id": new_id("prop"), "ts_utc": now_utc(), "t_sim_s": self.aux.t_s, "detection_id": det["id"],
                "origin": "watchdog", "intent": intent, "action_class": action_class, "magnitude": magnitude,
                "params": params or {}, "responsible": responsible, "reversible": ac.reversible,
                "status": "deliberating", "deliberation": None, "routing": None}
        if self.source.kind == "uci_replay" and self.source.row:
            ri = self.source.row.get("row_index")
            if ri is not None:
                prop["window"] = {"source_year": self.source.year, "start": max(0, int(ri) - 23), "end": int(ri) + 1}
        self.proposals.append(prop)
        self._event("proposal", f"agent-initiated proposal ({action_class}): {intent}", proposal_id=prop["id"],
                    detection_id=det["id"])
        aux_summary = self._aux_summary()
        if self.sync_deliberation:
            self._deliberate_and_route(det, prop, aux_summary)
        else:
            self._pool.submit(self._deliberate_and_route, det, prop, aux_summary)
        return det

    def _aux_summary(self) -> dict:
        return {"motors": {aid: {"state": m.state, "tagged_out": m.tagged_out, "winding_c": round(m.winding_c, 1),
                                 "current_a": round(m.current_a, 1)} for aid, m in self.aux.motors.items()},
                "unit": self._last_unit, "simulated": True}

    def _deliberate_and_route(self, det: dict, prop: dict, aux_summary: dict) -> None:
        try:
            res = delib.deliberate(det, prop, aux_summary, client=self.meta_client, backend=self.deliberation_backend)
        except Exception as exc:  # noqa: BLE001 - deliberate() should never raise; belt and braces
            ans = delib.offline_answer(det, prop).model_copy(update={"recommendation": "hold_for_human"})
            res = {"mode": "offline_fallback", "mode_label": f"error → held ({type(exc).__name__})",
                   "validated": False, "answer": ans.model_dump(), "errors": [type(exc).__name__]}
        with self._lock:
            prop["deliberation"] = res
            a = res["answer"]
            self._event("deliberation", f"{res['mode_label']}: recommendation {a['recommendation']} — "
                                        f"{a['summary'][:240]}", proposal_id=prop["id"])
            self._route(det, prop)

    def _route(self, det: dict, prop: dict) -> None:
        rec = prop["deliberation"]["answer"]["recommendation"]
        r = pol.decide(prop["action_class"], rec, self.policy)
        prop["routing"] = {"route": r.route, "policy_id": r.policy_id, "reason": r.reason}
        if r.route == "auto_execute_simulated":
            self._execute_simulated(det, prop, r.policy_id, approved_by="policy")
        else:
            self._human_required(det, prop, r.policy_id, r.reason, r.notify)

    def _execute_simulated(self, det: dict, prop: dict, policy_id: str, approved_by: str,
                           escalate_on_block: bool = True) -> Optional[dict]:
        if prop.get("action_class") != "simulated_auxiliary_switchover":  # defence in depth: nothing else executes
            raise ValueError(f"action class '{prop.get('action_class')}' is never executed by ThermoMind")
        p = prop["params"]
        ex = {"id": new_id("exe"), "ts_utc": now_utc(), "t_sim_s": self.aux.t_s, "proposal_id": prop["id"],
              "detection_id": det["id"], "what": prop["intent"], "where": pol.EXECUTION_WHERE,
              "policy_id": policy_id, "approved_by": approved_by, "reversible": True, "status": "in_progress",
              "notified": [], "interlocks": [], "simulated": True}
        try:
            sw = self.aux.request_switchover(p["group"], p["start"], p["stop"], new_id("sw"))
        except (InterlockError, KeyError, ValueError) as exc:
            ex["status"] = "blocked_by_interlock"
            ex["interlocks"] = [str(exc)]
            self.executions.append(ex)
            prop["status"] = "blocked_by_interlock"
            self._event("interlock", f"switchover blocked in simulator: {exc}", proposal_id=prop["id"],
                        execution_id=ex["id"])
            if escalate_on_block:
                self._human_required(det, prop, "WD-POL-002", f"simulated interlock blocked execution: {exc}",
                                     [*prop["responsible"], pol.OPERATOR, pol.SUPERVISOR])
            return ex
        ex["switchover_id"] = sw.id
        ex["interlocks"] = [f"start interlock passed for {p['start']} (not tagged out, no trip)",
                            f"minimum-flow interlock: {p['stop']} leaves service only after {p['start']} proves running"]
        self.executions.append(ex)
        self._exec_by_switchover[sw.id] = ex
        prop["status"] = "executing_in_simulator"
        msg = (f"EXECUTED IN SIMULATED AUXILIARIES ({policy_id}, approved by {approved_by}): {prop['intent']}. "
               f"{pol.HONESTY_STATEMENT}")
        ex["notified"] = self._notify([pol.OPERATOR, pol.SUPERVISOR, *prop["responsible"]], msg,
                                      {"execution_id": ex["id"], "proposal_id": prop["id"]})
        self._event("execution", f"executing in {pol.EXECUTION_WHERE} under {policy_id}: {prop['intent']}",
                    execution_id=ex["id"], proposal_id=prop["id"])
        self._event("notification", f"notified {', '.join(ex['notified'])} (simulated in-app)",
                    execution_id=ex["id"])
        return ex

    def _on_switchover_finished(self, sw: Any) -> None:
        ex = self._exec_by_switchover.get(sw.id)
        if ex is None:
            return
        ex["status"] = "completed" if sw.phase == "completed" else "aborted"
        ex["sequence_log"] = list(sw.log)
        ex["completed_t_sim_s"] = sw.finished_at_s
        for prop in self.proposals:
            if prop["id"] == ex["proposal_id"]:
                prop["status"] = "executed_in_simulator" if sw.phase == "completed" else "execution_aborted"
        if sw.phase == "completed":  # the overheating detection is resolved by the switchover
            for k, v in list(self._active.items()):
                if v["detection_id"] == ex["detection_id"]:
                    del self._active[k]
        self._event("execution", f"switchover {sw.phase} in simulated auxiliaries: " + " | ".join(sw.log),
                    execution_id=ex["id"])

    def _human_required(self, det: dict, prop: dict, policy_id: str, reason: str, notify: list[str]) -> dict:
        a = (prop.get("deliberation") or {}).get("answer") or {}
        task = {"id": new_id("hum"), "ts_utc": now_utc(), "t_sim_s": self.aux.t_s, "proposal_id": prop["id"],
                "detection_id": det["id"], "action_class": prop["action_class"], "intent": prop["intent"],
                "magnitude": prop["magnitude"], "policy_id": policy_id, "reason": reason,
                "recommendation": a.get("recommendation"), "summary": a.get("summary"),
                "conditions": a.get("conditions", []), "who_must_approve": a.get("who_must_approve", []),
                "responsible": prop["responsible"], "status": "awaiting_human", "decision": None, "notified": []}
        msg = (f"HUMAN DECISION REQUIRED ({policy_id}) — {det['kind']} on {det['asset']} [{det['severity']}]: "
               f"{prop['intent']}. Recommendation: {a.get('recommendation')}. ThermoMind executes nothing on any plant.")
        task["notified"] = self._notify(notify, msg, {"task_id": task["id"], "proposal_id": prop["id"]})
        self.human_tasks.append(task)
        if prop["status"] == "deliberating":
            prop["status"] = "awaiting_human"
        self._event("human_required", f"awaiting human ({policy_id}): {prop['intent']} — {reason}",
                    task_id=task["id"], proposal_id=prop["id"])
        self._event("notification", f"notified {', '.join(task['notified'])} (simulated in-app)", task_id=task["id"])
        return task

    # ------------------------------------------------------------------ public controls (simulation + monitor only)
    def decide(self, task_id: str, decision: str, persona: str, comment: Optional[str]) -> dict:
        with self._lock:
            task = next((t for t in self.human_tasks if t["id"] == task_id), None)
            if task is None:
                raise KeyError(f"human task '{task_id}' not found")
            if task["status"] != "awaiting_human":
                err = ValueError(f"task already decided ({task['status']})")
                err.status_code = 409  # type: ignore[attr-defined]
                raise err
            task["status"] = "approved" if decision == "approve" else "rejected"
            task["decision"] = {"decision": decision, "persona": persona, "comment": (comment or "")[:1000],
                                "ts_utc": now_utc()}
            prop = next((p for p in self.proposals if p["id"] == task["proposal_id"]), None)
            det = next((d for d in self.detections if d["id"] == task["detection_id"]), None)
            outcome = "recorded only — nothing executed on any plant"
            if decision == "approve" and prop and det and prop["action_class"] == "simulated_auxiliary_switchover":
                ex = self._execute_simulated(det, prop, "WD-POL-003", approved_by=persona, escalate_on_block=False)
                outcome = (f"executed in {pol.EXECUTION_WHERE} (human-approved, WD-POL-003)"
                           if ex and ex["status"] == "in_progress" else "blocked by simulated interlock")
            elif prop:
                prop["status"] = f"human_{task['status']}"
            task["decision"]["outcome"] = outcome
            self._event("decision", f"{persona} {task['status']} '{task['intent']}' — {outcome}", task_id=task_id)
            return task

    def inject_fault(self, asset: str, fault: str, rate_per_min: float, seed: int, initial_severity: float) -> dict:
        with self._lock:
            f = self.aux.inject_fault(asset, fault, rate_per_min, seed, initial_severity)
            self._event("fault_injected", f"SYNTHETIC {fault} injected on {asset} (rate {rate_per_min:g}/min, "
                                          f"seed {seed}) — simulator truth, not visible to detectors", asset=asset)
            return {"asset_id": f.asset_id, "kind": f.kind, "rate_per_min": f.rate_per_min, "seed": f.seed}

    def set_demand_step(self, mwh: float) -> None:
        with self._lock:
            self.demand_step_mwh = float(mwh)
            self._apply_demand()
            self._event("demand_step", f"simulated dispatch step set to {mwh:+.1f} MWh per hourly sample")

    def set_policy(self, auto: Optional[bool] = None, deliberation_backend: Optional[str] = None) -> None:
        with self._lock:
            if auto is not None:
                self.policy.auto_execute_simulated_switchover = bool(auto)
                self._event("policy", f"policy 'auto-execute low-risk switchovers in simulator' → "
                                      f"{'ON' if auto else 'OFF'}")
            if deliberation_backend is not None:
                self.deliberation_backend = deliberation_backend
                self._event("policy", f"deliberation backend → {deliberation_backend} (auto = shared deliberation "
                                      "feature for plant-level classes, built-in for the simulated switchover)")

    def tag_out(self, asset: str, tagged: bool) -> None:
        with self._lock:
            self.aux.set_tag_out(asset, tagged)
            self._event("control", f"{asset} {'tagged out' if tagged else 'tag removed'} (simulated LOTO)", asset=asset)

    def clear_fault(self, asset: str) -> None:
        with self._lock:
            n = self.aux.clear_faults(asset)
            self.aux.reset_trip(asset)
            self._event("control", f"simulated repair of {asset}: {n} fault(s) cleared, trip reset", asset=asset)

    # ------------------------------------------------------------------ views
    def state(self, history_points: int = 60, n_events: int = 60) -> dict[str, Any]:
        with self._lock:
            snap = self.aux.snapshot(history_points)
            return {
                "simulated": True,
                "honesty_statement": pol.HONESTY_STATEMENT,
                "running": self.running, "speed": self.speed, "sim_time_s": self.aux.t_s,
                "source": self.source.describe(),
                "auxiliaries": snap,
                "unit": self._last_unit,
                "policy": {"auto_execute_simulated_switchover": self.policy.auto_execute_simulated_switchover,
                           "table": pol.policy_table(self.policy)},
                "deliberation_backend": self.deliberation_backend,
                "deliberation_paths": {c: delib.choose_backend(self.deliberation_backend, c)
                                       for c in pol.ACTION_CLASSES},
                "detections": list(self.detections)[-50:],
                "proposals": list(self.proposals)[-50:],
                "executions": list(self.executions)[-50:],
                "human_tasks": list(self.human_tasks)[-50:],
                "notifications": list(self.outbox)[-50:],
                "events": list(self.events)[-n_events:],
                "counts": {"detections": len(self.detections), "proposals": len(self.proposals),
                           "executions": len(self.executions), "human_tasks": len(self.human_tasks),
                           "awaiting_human": sum(1 for t in self.human_tasks if t["status"] == "awaiting_human"),
                           "events": self.seq},
            }

    def events_since(self, n: int = 100, since_seq: int = 0) -> list[dict]:
        with self._lock:
            evs = [e for e in self.events if e["seq"] > since_seq]
            return evs[-n:]

    def stream_snapshot(self) -> dict[str, Any]:
        with self._lock:
            s = self.state(history_points=30, n_events=20)
            return s


_singleton: Optional[Watchdog] = None
_singleton_lock = threading.Lock()


def get_watchdog() -> Watchdog:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = Watchdog()
        return _singleton


def _set_watchdog(w: Optional[Watchdog]) -> None:
    """Test hook."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None and _singleton is not w:
            _singleton.shutdown()
        _singleton = w
