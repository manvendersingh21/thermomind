"""SIMULATED plant auxiliaries: lumped models of auxiliary motors (pumps, cooling-tower fans, lube-oil pump).

Everything in this module is a SIMULATION. No value here is a measurement from any plant, and no function here
reaches outside this process. The only "actions" (start / stop / switchover) change this in-memory model.

Per motor (all parameters are typical planning values — ASSUMPTIONS, not plant data):

* Electrical:   P_shaft = P_rated · load_frac + P_friction(bearing fault)
                P_in    = P_shaft / η                      I = P_in / (√3 · V · pf)
                P_cu    = P_cu,rated · (I / I_rated)²       (I²R stator copper loss)
* Winding thermal (first-order, single time constant — the same exponential form IEC 60255-149 thermal
  overload relays and IEEE C57.91 use):
                Δθ_ss = Δθ_rated · (I / I_rated)² · (1 + 0.6·s_ins) + Δθ_bearing(s_b)
                θ(t+Δt) = θ_ss + (θ(t) − θ_ss) · exp(−Δt / τ),   θ_ss = θ_amb + Δθ_ss
  Δθ_rated = 80 K is the class-B temperature rise (IEC 60034-1 Table 7 / NEMA MG-1 §12.43 style) applied to
  class-F (155 °C, IEC 60085) insulation — the usual "class-F insulation, class-B rise" margin practice.
  Alarm 130 °C and limit/trip 155 °C are TYPICAL settings, not plant-specific; confirm with the motor datasheet
  and protection settings.
* Insulation ageing: the "10-K rule" (Montsinger; Arrhenius form behind IEC 60216): relative ageing rate
  V = 2^((θ − θ_ref)/10) with θ_ref = 130 °C (class-F thermal class 155 °C minus a 25 K hot-spot allowance).
* Bearing / vibration: overall velocity RMS, zones per ISO 20816-3 (ex ISO 10816-3) group-2 rigid
  boundaries A/B 1.4, B/C 2.8, C/D 4.5 mm/s (typical, machine-specific in practice).
* Insulation resistance: IEEE Std 43 recommended minimum IR_1min ≈ (kV + 1) MΩ for older windings; we expose a
  simulated IR that falls with insulation degradation.

Faults (SYNTHETIC, injected by a seeded deterministic injector):
* bearing_degradation  — severity s_b grows at ``rate_per_min``: friction ↑ → current ↑, bearing heat into the
  end-windings ↑, vibration ↑ → winding temperature rises over minutes.
* insulation_degradation — s_ins grows: extra winding loss, insulation resistance ↓.
* belt_slip (fans)     — fan speed ratio r = 1 − 0.4·s: fan power ∝ r³ (affinity law) → current ↓, airflow ∝ r ↓.

Demand: the cooling-water duty is proportional to condenser heat rejection and the feedwater duty to steam flow.
Both come from ``app.simulator`` if it exposes a running engine (guarded import), otherwise from the replayed UCI
load (TEY, MWh per hourly sample, real public data) through the simulated historian, otherwise from a fixed
nominal profile. The fraction is ``d = TEY / rated`` (an ASSUMPTION: duties proportional to unit output).

Step: Δt = 1 s simulated. Ring buffers are bounded.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

SIMULATED_LABEL = "SIMULATED auxiliaries subsystem"
DT_S = 1.0
HISTORY_LEN = 1800  # samples per motor (30 simulated minutes at Δt = 1 s)
AMBIENT_ROOM_OFFSET_K = 5.0  # pump house / motor room above outdoor ambient (assumption)
AGEING_REF_C = 130.0
ALARM_C = 130.0
LIMIT_C = 155.0
VIB_ZONES = ((1.4, "A"), (2.8, "B"), (4.5, "C"))  # ISO 20816-3 group 2, rigid foundation (typical)
UNIT_RATED_MWH = 180.0  # generator rating per hourly sample (same default as the thermal feature)
STEAM_CYCLE_SHARE = 1.0 / 3.0  # CCGT steam-cycle share of unit output (typical 1/3; assumption)
MIN_FLOW_FRACTION = 0.25  # pump minimum continuous flow as a fraction of rated flow (typical 20–30 %)

FAULT_KINDS = ("bearing_degradation", "insulation_degradation", "belt_slip")
MOTOR_STATES = ("running", "starting", "standby", "stopped", "tripped")


@dataclass(frozen=True)
class MotorSpec:
    asset_id: str
    name: str
    group: str  # cooling_water | feedwater | ct_fans | lube_oil
    role: str  # duty | standby | shared | single
    rated_kw: float
    voltage_v: float
    efficiency: float
    power_factor: float
    tau_s: float
    load_law: str  # pump | fan | constant
    rated_rise_k: float = 80.0
    alarm_c: float = ALARM_C
    limit_c: float = LIMIT_C
    start_time_s: float = 5.0
    inrush_ratio: float = 5.5
    vib_base_mm_s: float = 1.1
    responsible_persona: str = "mechanical_maintenance_engineer"

    @property
    def rated_input_kw(self) -> float:
        return self.rated_kw / self.efficiency

    @property
    def rated_current_a(self) -> float:
        return self.rated_input_kw * 1000.0 / (math.sqrt(3.0) * self.voltage_v * self.power_factor)

    @property
    def rated_cu_loss_kw(self) -> float:
        # ~ half of the total rated losses are stator copper losses (typical split; assumption)
        return 0.5 * (self.rated_input_kw - self.rated_kw)


MOTOR_SPECS: list[MotorSpec] = [
    MotorSpec("CWP_A", "Cooling-water pump A", "cooling_water", "duty", 1400.0, 6600.0, 0.955, 0.87, 1500.0, "pump"),
    MotorSpec("CWP_B", "Cooling-water pump B", "cooling_water", "standby", 1400.0, 6600.0, 0.955, 0.87, 1500.0, "pump"),
    MotorSpec("BFP_A", "Boiler feedwater pump A", "feedwater", "duty", 2200.0, 6600.0, 0.96, 0.88, 1800.0, "pump"),
    MotorSpec("BFP_B", "Boiler feedwater pump B", "feedwater", "standby", 2200.0, 6600.0, 0.96, 0.88, 1800.0, "pump"),
    MotorSpec("CTF_1", "Cooling-tower fan 1", "ct_fans", "shared", 132.0, 400.0, 0.945, 0.85, 900.0, "fan"),
    MotorSpec("CTF_2", "Cooling-tower fan 2", "ct_fans", "shared", 132.0, 400.0, 0.945, 0.85, 900.0, "fan"),
    MotorSpec("CTF_3", "Cooling-tower fan 3", "ct_fans", "shared", 132.0, 400.0, 0.945, 0.85, 900.0, "fan"),
    MotorSpec("LOP", "Lube-oil pump", "lube_oil", "single", 45.0, 400.0, 0.93, 0.85, 600.0, "constant"),
]
SPEC_BY_ID = {s.asset_id: s for s in MOTOR_SPECS}
GROUPS = {
    "cooling_water": {"name": "Cooling-water pumps (2 × 100 %)", "duty_from": "condenser heat rejection"},
    "feedwater": {"name": "Boiler feedwater pumps (2 × 100 %)", "duty_from": "steam flow"},
    "ct_fans": {"name": "Cooling-tower fans (3 × 33 %)", "duty_from": "condenser heat rejection"},
    "lube_oil": {"name": "Lube-oil pump", "duty_from": "constant"},
}


def vibration_zone(v_mm_s: float) -> str:
    for bound, zone in VIB_ZONES:
        if v_mm_s <= bound:
            return zone
    return "D"


def ageing_rate(theta_c: float) -> float:
    """10-K rule: relative insulation ageing rate 2^((θ − 130)/10); 1.0 at 130 °C."""
    return float(2.0 ** ((theta_c - AGEING_REF_C) / 10.0))


def steady_state_rise_k(spec: MotorSpec, current_ratio: float, s_ins: float = 0.0, s_bearing: float = 0.0) -> float:
    """Δθ_ss = Δθ_rated·(I/I_r)²·(1 + 0.6·s_ins) + 40·s_b (bearing heat conducted into the end-windings)."""
    return spec.rated_rise_k * current_ratio ** 2 * (1.0 + 0.6 * s_ins) + 40.0 * s_bearing


def first_order_step(theta: float, theta_ss: float, tau_s: float, dt_s: float = DT_S) -> float:
    """Exact step of dθ/dt = (θ_ss − θ)/τ for piecewise-constant input."""
    return theta_ss + (theta - theta_ss) * math.exp(-dt_s / tau_s)


def time_to_reach_s(theta: float, theta_ss: float, target: float, tau_s: float) -> Optional[float]:
    """Time for a first-order response from θ toward θ_ss to cross ``target``; None if it never does."""
    if theta >= target:
        return 0.0
    if theta_ss <= target:
        return None
    return float(tau_s * math.log((theta_ss - theta) / (theta_ss - target)))


def load_fraction(spec: MotorSpec, demand: float, n_running_in_group: int, speed_ratio: float = 1.0) -> float:
    """Shaft load as a fraction of rated output.

    pump: constant-speed centrifugal pump, P ≈ 0.35 + 0.65·q (q = flow fraction carried by this pump).
    fan: fixed-blade fan at speed ratio r, P ≈ (0.5 + 0.5·d)·r³ (affinity law).
    constant: 0.8 (lube-oil pump)."""
    d = max(0.0, demand)
    if spec.load_law == "pump":
        q = d / max(1, n_running_in_group)
        return 0.35 + 0.65 * min(q, 1.3)
    if spec.load_law == "fan":
        return (0.5 + 0.5 * min(d, 1.3)) * speed_ratio ** 3
    return 0.8


@dataclass
class Fault:
    kind: str
    asset_id: str
    rate_per_min: float
    seed: int
    severity: float = 0.0
    injected_at_s: float = 0.0
    rng: Any = None

    def advance(self, dt_s: float) -> None:
        if self.rng is None:
            self.rng = np.random.default_rng(self.seed)
        jitter = 1.0 + 0.2 * float(self.rng.standard_normal())
        self.severity = float(min(1.0, max(0.0, self.severity + self.rate_per_min * dt_s / 60.0 * jitter)))


@dataclass
class Motor:
    spec: MotorSpec
    state: str
    winding_c: float
    tagged_out: bool = False
    state_since_s: float = 0.0
    current_a: float = 0.0
    load_frac: float = 0.0
    speed_ratio: float = 1.0
    vibration_mm_s: float = 0.0
    bearing_c: float = 0.0
    insulation_mohm: float = 2000.0
    loss_of_life_h: float = 0.0
    trip_reason: Optional[str] = None
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))

    @property
    def running(self) -> bool:
        return self.state in ("running", "starting")


class InterlockError(ValueError):
    """An interlock in the simulated auxiliaries blocked the requested operation (HTTP 409)."""

    status_code = 409


@dataclass
class Switchover:
    """Two-phase sequence: start the standby, prove it running, then stop the duty pump (min-flow continuity)."""

    id: str
    group: str
    start_id: str
    stop_id: str
    requested_at_s: float
    phase: str = "starting_standby"  # starting_standby -> stopping_duty -> completed | aborted
    log: list[str] = field(default_factory=list)
    finished_at_s: Optional[float] = None


class AuxiliariesModel:
    """In-memory SIMULATED auxiliaries. Not thread-safe by itself: the Watchdog holds a lock around it."""

    def __init__(self, ambient_c: float = 15.0, seed: int = 7):
        self.seed = int(seed)
        self._rng = np.random.default_rng(self.seed)
        self.t_s = 0.0
        self.ambient_c = float(ambient_c)
        self.cooling_demand = 0.74
        self.feedwater_demand = 0.74
        self.faults: dict[tuple[str, str], Fault] = {}
        self.switchovers: deque[Switchover] = deque(maxlen=50)
        self.motors: dict[str, Motor] = {}
        self.trip_log: deque[dict] = deque(maxlen=100)
        for spec in MOTOR_SPECS:
            state = "standby" if spec.role == "standby" else "running"
            m = Motor(spec=spec, state=state, winding_c=self.ambient_c + AMBIENT_ROOM_OFFSET_K)
            self.motors[spec.asset_id] = m
        self._settle()

    # ------------------------------------------------------------------ helpers
    def _settle(self) -> None:
        """Start from thermal steady state at the initial demand (no artificial warm-up transient)."""
        for m in self.motors.values():
            self._electrical(m)
            if m.running:
                m.winding_c = self._theta_ss(m)

    def group_members(self, group: str) -> list[Motor]:
        if not hasattr(self, "_groups"):
            self._groups: dict[str, list[Motor]] = {}
            for m in self.motors.values():
                self._groups.setdefault(m.spec.group, []).append(m)
        return self._groups.get(group, [])

    def n_running(self, group: str) -> int:
        return sum(1 for m in self.group_members(group) if m.running)

    def _demand_for(self, spec: MotorSpec) -> float:
        if spec.group == "feedwater":
            return self.feedwater_demand
        if spec.group in ("cooling_water", "ct_fans"):
            return self.cooling_demand
        return 1.0

    def fault_severity(self, asset_id: str, kind: str) -> float:
        f = self.faults.get((asset_id, kind))
        return f.severity if f else 0.0

    def expected_current_a(self, asset_id: str) -> float:
        """Healthy-model current at the present demand (what a model-based watchdog expects)."""
        m = self.motors[asset_id]
        spec = m.spec
        n = max(1, self.n_running(spec.group)) if spec.load_law == "pump" else 1
        lf = load_fraction(spec, self._demand_for(spec), n, 1.0)
        p_in = spec.rated_kw * lf / spec.efficiency
        return p_in * 1000.0 / (math.sqrt(3.0) * spec.voltage_v * spec.power_factor)

    def _electrical(self, m: Motor) -> None:
        spec = m.spec
        s_b = self.fault_severity(spec.asset_id, "bearing_degradation")
        s_slip = self.fault_severity(spec.asset_id, "belt_slip")
        m.speed_ratio = 1.0 - 0.4 * s_slip if spec.load_law == "fan" else 1.0
        amb = self.ambient_c + AMBIENT_ROOM_OFFSET_K
        if not m.running:
            m.current_a = 0.0
            m.load_frac = 0.0
            m.vibration_mm_s = 0.0
            m.bearing_c = first_order_step(m.bearing_c or amb, amb, 900.0)
            return
        n = max(1, self.n_running(spec.group)) if spec.load_law == "pump" else 1
        lf = load_fraction(spec, self._demand_for(spec), n, m.speed_ratio)
        friction_kw = 0.35 * spec.rated_kw * s_b
        p_shaft = spec.rated_kw * lf + friction_kw
        p_in = p_shaft / spec.efficiency
        i = p_in * 1000.0 / (math.sqrt(3.0) * spec.voltage_v * spec.power_factor)
        if m.state == "starting":  # direct-on-line start: inrush decaying over the start time
            prog = min(1.0, (self.t_s - m.state_since_s) / spec.start_time_s)
            i = i + (spec.inrush_ratio - 1.0) * spec.rated_current_a * (1.0 - prog)
        noise = 1.0 + 0.004 * float(self._rng.standard_normal())
        m.current_a = max(0.0, i * noise)
        m.load_frac = p_shaft / spec.rated_kw
        m.vibration_mm_s = max(0.2, spec.vib_base_mm_s + 7.5 * s_b ** 1.5 + 2.0 * s_slip
                               + 0.05 * float(self._rng.standard_normal()))
        m.bearing_c = first_order_step(m.bearing_c or amb, amb + 30.0 * lf + 60.0 * s_b, 900.0)

    def _theta_ss(self, m: Motor) -> float:
        if not m.running:
            return self.ambient_c + AMBIENT_ROOM_OFFSET_K
        ratio = m.current_a / m.spec.rated_current_a
        s_ins = self.fault_severity(m.spec.asset_id, "insulation_degradation")
        s_b = self.fault_severity(m.spec.asset_id, "bearing_degradation")
        return self.ambient_c + AMBIENT_ROOM_OFFSET_K + steady_state_rise_k(m.spec, ratio, s_ins, s_b)

    # ------------------------------------------------------------------ public ops (simulation only)
    def inject_fault(self, asset_id: str, kind: str, rate_per_min: float = 0.05, seed: int = 11,
                     initial_severity: float = 0.0) -> Fault:
        if asset_id not in self.motors:
            raise KeyError(f"unknown auxiliary '{asset_id}' (expected one of {', '.join(self.motors)})")
        if kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault '{kind}' (expected one of {', '.join(FAULT_KINDS)})")
        if kind == "belt_slip" and self.motors[asset_id].spec.load_law != "fan":
            raise ValueError("belt_slip applies only to cooling-tower fans (CTF_1..CTF_3)")
        if not (0.0 <= rate_per_min <= 1.0) or not math.isfinite(rate_per_min):
            raise ValueError("rate_per_min must be within [0, 1] severity per simulated minute")
        f = Fault(kind=kind, asset_id=asset_id, rate_per_min=float(rate_per_min), seed=int(seed),
                  severity=float(min(1.0, max(0.0, initial_severity))), injected_at_s=self.t_s)
        self.faults[(asset_id, kind)] = f
        return f

    def clear_faults(self, asset_id: Optional[str] = None) -> int:
        keys = [k for k in self.faults if asset_id is None or k[0] == asset_id]
        for k in keys:
            del self.faults[k]
        return len(keys)

    def set_tag_out(self, asset_id: str, tagged: bool) -> Motor:
        m = self.motors[asset_id]
        if tagged and m.running:
            raise InterlockError(f"{asset_id} is running; stop it before applying a tag-out (simulated LOTO)")
        m.tagged_out = bool(tagged)
        if not tagged and m.state in ("stopped",) and m.spec.role == "standby":
            self._set_state(m, "standby")
        return m

    def can_start(self, asset_id: str) -> tuple[bool, list[str]]:
        m = self.motors[asset_id]
        reasons = []
        if m.tagged_out:
            reasons.append(f"interlock: {asset_id} is tagged out (simulated LOTO) — start blocked")
        if m.state == "tripped":
            reasons.append(f"interlock: {asset_id} protection trip not reset — start blocked")
        if m.running:
            reasons.append(f"{asset_id} is already running")
        return (not reasons), reasons

    def can_stop(self, asset_id: str) -> tuple[bool, list[str]]:
        """Minimum-flow interlock: a 2×100 % pump may stop only if another pump in its group is proven running
        and the remaining pumps can carry the demanded flow."""
        m = self.motors[asset_id]
        reasons = []
        if not m.running:
            reasons.append(f"{asset_id} is not running")
        if m.spec.load_law == "pump" and m.spec.group in ("cooling_water", "feedwater"):
            others = [o for o in self.group_members(m.spec.group) if o is not m and o.state == "running"]
            demand = self._demand_for(m.spec)
            if not others:
                reasons.append(f"interlock (minimum flow): no other {m.spec.group} pump proven running — "
                               f"stopping {asset_id} would drop header flow below the minimum")
            elif demand > 1.3 * len(others):
                reasons.append(f"interlock (minimum flow): remaining pumps cannot carry demand {demand:.2f}")
        return (not reasons), reasons

    def start(self, asset_id: str) -> Motor:
        ok, reasons = self.can_start(asset_id)
        if not ok:
            raise InterlockError("; ".join(reasons))
        m = self.motors[asset_id]
        self._set_state(m, "starting")
        return m

    def stop(self, asset_id: str, to_state: str = "stopped") -> Motor:
        ok, reasons = self.can_stop(asset_id)
        if not ok:
            raise InterlockError("; ".join(reasons))
        m = self.motors[asset_id]
        self._set_state(m, to_state)
        return m

    def reset_trip(self, asset_id: str) -> Motor:
        m = self.motors[asset_id]
        if m.state == "tripped":
            m.trip_reason = None
            self._set_state(m, "standby" if m.spec.role in ("standby", "duty") else "stopped")
        return m

    def request_switchover(self, group: str, start_id: str, stop_id: str, sw_id: str) -> Switchover:
        """Validate the start interlocks now and begin the two-phase sequence. Raises InterlockError."""
        for aid in (start_id, stop_id):
            if aid not in self.motors:
                raise KeyError(f"unknown auxiliary '{aid}'")
        if self.motors[start_id].spec.group != group or self.motors[stop_id].spec.group != group:
            raise ValueError("switchover assets must belong to the same group")
        ok, reasons = self.can_start(start_id)
        if not ok:
            raise InterlockError("; ".join(reasons))
        sw = Switchover(id=sw_id, group=group, start_id=start_id, stop_id=stop_id, requested_at_s=self.t_s)
        self.start(start_id)
        sw.log.append(f"t={self.t_s:.0f}s start {start_id} (DOL start, inrush {self.motors[start_id].spec.inrush_ratio:g}× "
                      f"for {self.motors[start_id].spec.start_time_s:g}s)")
        self.switchovers.append(sw)
        return sw

    def _advance_switchovers(self) -> list[Switchover]:
        finished = []
        for sw in self.switchovers:
            if sw.phase in ("completed", "aborted"):
                continue
            st = self.motors[sw.start_id]
            if sw.phase == "starting_standby":
                if st.state == "running":
                    sw.phase = "stopping_duty"
                    sw.log.append(f"t={self.t_s:.0f}s {sw.start_id} proven running (current settled)")
                elif st.state not in ("starting",):
                    sw.phase = "aborted"
                    sw.finished_at_s = self.t_s
                    sw.log.append(f"t={self.t_s:.0f}s abort: {sw.start_id} failed to prove running ({st.state}); "
                                  f"{sw.stop_id} left as is")
                    finished.append(sw)
                    continue
            if sw.phase == "stopping_duty":
                du = self.motors[sw.stop_id]
                if not du.running:
                    sw.log.append(f"t={self.t_s:.0f}s {sw.stop_id} already not running ({du.state})")
                    sw.phase = "completed"
                else:
                    ok, reasons = self.can_stop(sw.stop_id)
                    if ok:
                        self._set_state(du, "stopped")
                        sw.log.append(f"t={self.t_s:.0f}s stop {sw.stop_id} → out of service (min-flow interlock "
                                      f"satisfied by {sw.start_id})")
                        sw.phase = "completed"
                    else:
                        sw.log.append(f"t={self.t_s:.0f}s waiting: {'; '.join(reasons)}")
                        if self.t_s - sw.requested_at_s > 120:
                            sw.phase = "aborted"
                if sw.phase in ("completed", "aborted"):
                    sw.finished_at_s = self.t_s
                    finished.append(sw)
        return finished

    def _set_state(self, m: Motor, state: str) -> None:
        if state not in MOTOR_STATES:
            raise ValueError(f"bad motor state {state}")
        m.state = state
        m.state_since_s = self.t_s

    # ------------------------------------------------------------------ dynamics
    def set_demand(self, cooling: float, feedwater: float, ambient_c: Optional[float] = None) -> None:
        self.cooling_demand = float(min(1.3, max(0.0, cooling)))
        self.feedwater_demand = float(min(1.3, max(0.0, feedwater)))
        if ambient_c is not None and math.isfinite(ambient_c):
            self.ambient_c = float(ambient_c)

    def step(self, dt_s: float = DT_S) -> dict[str, list]:
        """Advance the simulation by ``dt_s`` seconds. Returns {'trips': [...], 'switchovers': [...]}"""
        self.t_s += dt_s
        for f in self.faults.values():
            f.advance(dt_s)
        trips = []
        for m in self.motors.values():
            if m.state == "starting" and self.t_s - m.state_since_s >= m.spec.start_time_s:
                self._set_state(m, "running")
            self._electrical(m)
            m.winding_c = first_order_step(m.winding_c, self._theta_ss(m), m.spec.tau_s, dt_s)
            s_ins = self.fault_severity(m.spec.asset_id, "insulation_degradation")
            m.insulation_mohm = max(0.5, 2000.0 * (1.0 - s_ins) ** 3 + 0.5)
            if m.running:
                m.loss_of_life_h += ageing_rate(m.winding_c) * dt_s / 3600.0
                if m.winding_c >= m.spec.limit_c:  # thermal overload relay (IEC 60255-149 style), set at limit
                    m.trip_reason = f"thermal overload: winding {m.winding_c:.1f} °C ≥ {m.spec.limit_c:.0f} °C"
                    self._set_state(m, "tripped")
                    m.current_a = 0.0
                    trips.append({"asset_id": m.spec.asset_id, "t_s": self.t_s, "reason": m.trip_reason})
                    self.trip_log.append(trips[-1])
            m.history.append((self.t_s, round(m.winding_c, 3), round(m.current_a, 2), round(m.vibration_mm_s, 3)))
        return {"trips": trips, "switchovers": self._advance_switchovers()}

    # ------------------------------------------------------------------ unit capability coupling
    def group_capacity(self, group: str) -> float:
        members = self.group_members(group)
        if group == "ct_fans":
            return sum(m.speed_ratio for m in members if m.state == "running") / max(1, len(members))
        if group == "lube_oil":
            return 1.0 if any(m.running for m in members) else 0.0
        return float(min(1.0, sum(1.0 for m in members if m.state == "running")))

    def unit_capability(self) -> dict[str, Any]:
        """Output the unit could deliver given the auxiliaries (MWh per hourly sample, same unit as TEY).

        cooling = min(CW pump capacity, 0.55 + 0.45·fan airflow fraction)
        available = rated · ((1 − s) + s · min(cooling, feedwater)),  s = steam-cycle share (assumption 1/3).
        """
        cw = self.group_capacity("cooling_water")
        fw = self.group_capacity("feedwater")
        fans = self.group_capacity("ct_fans")
        cooling = min(cw, 0.55 + 0.45 * fans)
        steam_factor = min(cooling, fw)
        avail = UNIT_RATED_MWH * ((1.0 - STEAM_CYCLE_SHARE) + STEAM_CYCLE_SHARE * steam_factor)
        if self.group_capacity("lube_oil") == 0.0:
            avail = 0.0
        binding = "nameplate"
        if avail < UNIT_RATED_MWH - 1e-6:
            binding = "lube_oil" if avail == 0.0 else ("cooling" if cooling <= fw else "feedwater")
        return {"rated_mwh": UNIT_RATED_MWH, "aux_limited_mwh": round(avail, 2), "cooling_capacity_frac": round(cooling, 3),
                "cw_capacity_frac": round(cw, 3), "fan_airflow_frac": round(fans, 3),
                "feedwater_capacity_frac": round(fw, 3), "aux_binding": binding}

    # ------------------------------------------------------------------ views
    def motor_view(self, m: Motor, history_points: int = 60) -> dict[str, Any]:
        spec = m.spec
        exp_i = self.expected_current_a(spec.asset_id) if m.state == "running" else None
        hist = list(m.history)
        step = max(1, len(hist) // history_points) if hist else 1
        ds = hist[::step][-history_points:]
        ratio = m.current_a / spec.rated_current_a if spec.rated_current_a else 0.0
        cu = spec.rated_cu_loss_kw * ratio ** 2 if m.running else 0.0
        return {
            "asset_id": spec.asset_id, "name": spec.name, "group": spec.group, "role": spec.role,
            "state": m.state, "tagged_out": m.tagged_out, "running": m.running,
            "rated_kw": spec.rated_kw, "voltage_v": spec.voltage_v,
            "current_a": round(m.current_a, 2), "rated_current_a": round(spec.rated_current_a, 2),
            "current_ratio": round(ratio, 4),
            "expected_current_a": None if exp_i is None else round(exp_i, 2),
            "load_frac": round(m.load_frac, 4), "i2r_loss_kw": round(cu, 2),
            "winding_c": round(m.winding_c, 2), "alarm_c": spec.alarm_c, "limit_c": spec.limit_c,
            "tau_s": spec.tau_s, "bearing_c": round(m.bearing_c, 2),
            "vibration_mm_s": round(m.vibration_mm_s, 3),
            "vibration_zone": vibration_zone(m.vibration_mm_s) if m.running else None,
            "insulation_mohm": round(m.insulation_mohm, 1),
            "speed_ratio": round(m.speed_ratio, 4),
            "loss_of_life_h": round(m.loss_of_life_h, 5),
            "trip_reason": m.trip_reason,
            "responsible_persona": spec.responsible_persona,
            "history": [{"t_s": h[0], "winding_c": h[1], "current_a": h[2], "vibration_mm_s": h[3]} for h in ds],
        }

    def snapshot(self, history_points: int = 60) -> dict[str, Any]:
        return {
            "simulated": True,
            "label": SIMULATED_LABEL,
            "t_s": self.t_s,
            "ambient_c": round(self.ambient_c, 2),
            "room_offset_k": AMBIENT_ROOM_OFFSET_K,
            "cooling_demand_frac": round(self.cooling_demand, 4),
            "feedwater_demand_frac": round(self.feedwater_demand, 4),
            "motors": [self.motor_view(m, history_points) for m in self.motors.values()],
            "groups": [{"group": g, **info, "running": self.n_running(g), "capacity_frac": round(self.group_capacity(g), 3)}
                       for g, info in GROUPS.items()],
            "unit": self.unit_capability(),
            "switchovers": [{"id": s.id, "group": s.group, "start": s.start_id, "stop": s.stop_id, "phase": s.phase,
                             "requested_at_s": s.requested_at_s, "finished_at_s": s.finished_at_s, "log": list(s.log)}
                            for s in list(self.switchovers)[-10:]],
            "injected_faults": [{"asset_id": f.asset_id, "kind": f.kind, "severity": round(f.severity, 4),
                                 "rate_per_min": f.rate_per_min, "seed": f.seed, "injected_at_s": f.injected_at_s,
                                 "note": "SYNTHETIC injected fault (simulator truth; detectors do not read this)"}
                                for f in self.faults.values()],
        }
