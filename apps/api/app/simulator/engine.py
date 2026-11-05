"""Simulation engine: replays real UCI ambient inputs + dispatch, integrates the SIMULATED plant with RK4.

Acts on the software model only — there is no connection to any real plant, PLC, DCS or historian.

Dynamics (states x = [ω, z, λ], dt = 1 s, classical RK4):
  Rotor (swing equation, per-unit on P_rated, H = 5 s):
      2H·ω·dω/dt = (P_m − P_e/η_g)/P_rated
  Electrical load drawn (dispatch setpoint with load-frequency damping D):
      P_e = P_sp·(1 + D·(ω − 1))
  Governor — the simulated plant's own control (droop R + PI secondary loop, anti-windup):
      λ_cmd = clip(z + (1 − ω)/R, 0, 1),   dz/dt = K_i·(1 − ω)
  Fuel/IGV actuator lag:  dλ/dt = (λ_cmd − λ)/τ_a
  The combustor balance (physics.plant) turns λ into the TIT target and the fuel flow needed to reach it.

Dispatch setpoint P_sp = real TEY of the replayed row (MWh per hourly sample ≈ mean MW), clipped to the
model's available capacity at current ambient/fault conditions (labelled ``dispatch_clipped``).
Replay: ``rows_per_hour`` real rows per simulated hour (each row is held for 3600/rows_per_hour s).

Energy closure per step (RK4-stage-weighted, ref. 300 K, fuel at 300 K):
  E_in = ṁ_f·LHV
  E_out = (ṁ_g·h4 − ṁ_a·h1) + (1 − η_b)·ṁ_f·LHV + P_loss + P_e/η_g + ΔKE/dt,   KE = H·P_rated·ω²
  closure_pct = |E_in − E_out| / E_in · 100   (a numerical consistency check of the cycle + rotor balance)
"""
from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections import deque

import numpy as np

from app.schemas import MEASUREMENT_KEYS
from app.simulator import calibration as cal
from app.simulator import physics as ph

H = 5.0
DROOP_R = 0.05
KI = 0.5
D_LOAD = 2.0
TAU_ACT = 2.0
DT = 1.0
BUFFER_MAX = 20_000
MAX_STEPS_PER_TICK = 2_000
INPUT_CHANNELS = ("AT", "AP", "AH")
PHYSICS_FAULTS = ("intake_fouling", "compressor_fouling", "hot_day")
SENSOR_FAULTS = ("sensor_bias", "sensor_drift", "sensor_spike", "sensor_stuck")
FAULT_KINDS = PHYSICS_FAULTS + SENSOR_FAULTS
SENSOR_MAG_MAX = 1.0e4  # sensor-fault magnitude bound (channel units) so values stay finite / JSON-safe
FOUL_MAX = 100.0        # intake fouling factor cap (filter ΔP ≈ 100x clean; beyond this p1 -> 0)
DAT_MAX = 25.0          # total synthetic +ΔAT across stacked hot_day faults
CONTROL_LABEL = "simulated plant's own control (software model only; no real plant is controlled)"


class SimError(ValueError):
    """Bad simulator request (mapped to 422)."""


class SimEngine:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.buffer: deque[dict] = deque(maxlen=BUFFER_MAX)
        self.faults: dict[str, dict] = {}
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self.params: dict | None = None
        self._arrays: tuple | None = None
        self.status = "idle"  # idle | running | paused | stopped | finished
        self.speed = 60.0     # simulated seconds per wall second
        self.rows_per_hour = 60
        self.year = 2014
        self.start_index = 0
        self._reset_state()

    # ------------------------------------------------------------------ state
    def _reset_state(self) -> None:
        self.sim_t = 0.0
        self.omega, self.z, self.lam = 1.0, 0.5, 0.5
        self.initialised = False
        self.last_record: dict | None = None
        self.steps = 0

    def _ensure_params(self) -> dict:
        if self.params is None:
            self.params, _ = cal.get_calibration()
        return self.params

    def configure(self, year: int | None = None, start_index: int | None = None, speed: float | None = None,
                  rows_per_hour: int | None = None) -> None:
        with self.lock:
            try:
                n = len(cal.year_frame(int(year if year is not None else self.year)))
            except KeyError as exc:
                raise SimError(str(exc)) from None
            if year is not None:
                self.year = int(year)
            if start_index is not None:
                if not 0 <= int(start_index) < n:
                    raise SimError(f"start_index must be in [0, {n}) for year {self.year}")
                self.start_index = int(start_index)
            if speed is not None:
                self.speed = float(speed)
            if rows_per_hour is not None:
                self.rows_per_hour = int(rows_per_hour)

    def row_ptr(self) -> int:
        return self.start_index + int(self.sim_t // (3600.0 / self.rows_per_hour))

    # ------------------------------------------------------------------ faults
    def add_fault(self, kind: str, magnitude: float, channel: str | None = None) -> dict:
        if kind not in FAULT_KINDS:
            raise SimError(f"unknown fault kind '{kind}' (expected one of {', '.join(FAULT_KINDS)})")
        if not np.isfinite(magnitude):
            raise SimError("magnitude must be finite")
        if kind in SENSOR_FAULTS:
            if channel not in MEASUREMENT_KEYS:
                raise SimError(f"sensor faults need channel in {MEASUREMENT_KEYS}")
        elif channel is not None:
            raise SimError("channel is only valid for sensor_* faults")
        if kind == "intake_fouling" and not 0 <= magnitude <= 100:
            raise SimError("intake_fouling magnitude is a fouling-factor rate per simulated hour in [0, 100]")
        if kind == "compressor_fouling" and not 0 <= magnitude <= 0.2:
            raise SimError("compressor_fouling magnitude is a fractional efficiency loss in [0, 0.2]")
        if kind == "hot_day" and not 0 <= magnitude <= 25:
            raise SimError("hot_day magnitude is +ΔAT in °C, [0, 25]")
        if kind in SENSOR_FAULTS and abs(magnitude) > SENSOR_MAG_MAX:
            raise SimError(f"sensor fault magnitude must be within ±{SENSOR_MAG_MAX:g} (channel units)")
        with self.lock:
            fid = "flt_" + uuid.uuid4().hex[:10]
            f = {"id": fid, "kind": kind, "magnitude": float(magnitude), "channel": channel,
                 "start_sim_t": self.sim_t, "synthetic": True, "stuck_value": None,
                 "_rng": np.random.default_rng(int(fid[4:], 16))}
            self.faults[fid] = f
            return self._public_fault(f)

    def remove_fault(self, fid: str) -> bool:
        with self.lock:
            return self.faults.pop(fid, None) is not None

    @staticmethod
    def _public_fault(f: dict) -> dict:
        return {k: v for k, v in f.items() if not k.startswith("_")}

    def _physics_faults(self) -> tuple[float, float, float]:
        foul = comp = dAT = 0.0
        for f in self.faults.values():
            if f["kind"] == "intake_fouling":
                foul += f["magnitude"] * max(0.0, self.sim_t - f["start_sim_t"]) / 3600.0
            elif f["kind"] == "compressor_fouling":
                comp += f["magnitude"]
            elif f["kind"] == "hot_day":
                dAT += f["magnitude"]
        # caps keep stacked/long-running synthetic faults inside the model's valid (finite) domain
        return min(foul, FOUL_MAX), min(comp, 0.3), min(dAT, DAT_MAX)

    # ------------------------------------------------------------------ physics step
    def _inputs(self) -> dict:
        if self._arrays is None or self._arrays[0] != self.year:
            f = cal.year_frame(self.year)
            self._arrays = (self.year, {k: f[k].to_numpy(dtype=float) for k in ("AT", "AP", "AH", "TEY")})
        arr = self._arrays[1]
        ptr = self.row_ptr()
        if ptr >= len(arr["AT"]):
            return {}
        return {"row_index": ptr, **{k: float(v[ptr]) for k, v in arr.items()}}

    def capacity(self, AT: float, AP: float, AH: float, foul: float, comp: float) -> float:
        p = self._ensure_params()
        return float(ph.plant(p, AT, AP, AH, 1.0, 1.0, foul, comp)["P_elec_ss"])

    def _deriv(self, x, AT, AP, AH, sp, foul, comp):
        p = self.params
        w, z, lam = (float(v) for v in x)
        lam_c = min(max(lam, 0.0), 1.0)
        r = ph.plant(p, AT, AP, AH, lam_c, w, foul, comp)
        P_e = sp * (1.0 + D_LOAD * (w - 1.0))
        dw = (float(r["P_mech"]) - P_e / p["eta_g"]) / (2.0 * H * p["P_rated"] * w)
        lam_cmd_raw = z + (1.0 - w) / DROOP_R
        dz = KI * (1.0 - w)
        if (z >= 1.0 and dz > 0) or (z <= 0.0 and dz < 0):
            dz = 0.0
        dlam = (min(max(lam_cmd_raw, 0.0), 1.0) - lam) / TAU_ACT
        m_f = float(r["m_fuel"])
        e_in = m_f * ph.LHV / 1e6
        e_out = ((float(r["m_gas"]) * float(r["h4"]) - float(r["m_air"]) * float(r["h1"])) / 1e6
                 + (1 - ph.ETA_B) * e_in + p["P_loss"] + P_e / p["eta_g"])
        return np.array([dw, dz, dlam]), {"r": r, "P_e": P_e, "e_in": e_in, "e_out": e_out}

    def _init_steady(self, inp: dict, foul: float, comp: float, dAT: float, sp_req: float) -> None:
        p = self._ensure_params()
        AT = inp["AT"] + dAT
        sp = min(sp_req, 0.999 * self.capacity(AT, inp["AP"], inp["AH"], foul, comp))
        lam = float(cal.solve_lambda(p, AT, inp["AP"], inp["AH"], sp, foul, comp)[0])
        lam = min(max(lam, 0.0), 1.0)
        self.omega, self.z, self.lam = 1.0, lam, lam
        self.initialised = True

    def step(self, setpoint_override: float | None = None) -> dict | None:
        """Advance one simulated second. Returns the StepRecord, or None when the replay year is exhausted."""
        with self.lock:
            p = self._ensure_params()
            inp = self._inputs()
            if not inp:
                self.status = "finished"
                return None
            foul, comp, dAT = self._physics_faults()
            req = inp["TEY"] if setpoint_override is None else float(setpoint_override)
            if not self.initialised:
                self._init_steady(inp, foul, comp, dAT, req)
            AT, AP, AH = inp["AT"] + dAT, inp["AP"], inp["AH"]
            cap = self.capacity(AT, AP, AH, foul, comp)
            sp = min(req, 0.999 * cap)
            x0 = np.array([self.omega, self.z, self.lam])
            args = (AT, AP, AH, sp, foul, comp)
            k1, a1 = self._deriv(x0, *args)
            k2, a2 = self._deriv(x0 + 0.5 * DT * k1, *args)
            k3, a3 = self._deriv(x0 + 0.5 * DT * k2, *args)
            k4, a4 = self._deriv(x0 + DT * k3, *args)
            x1 = x0 + DT / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
            x1[1] = min(max(x1[1], 0.0), 1.0)

            def w_avg(key: str) -> float:
                return (a1[key] + 2 * a2[key] + 2 * a3[key] + a4[key]) / 6.0

            dKE = H * p["P_rated"] * (x1[0] ** 2 - x0[0] ** 2) / DT
            e_in = w_avg("e_in")
            closure = abs(e_in - w_avg("e_out") - dKE) / e_in * 100.0
            self.omega, self.z, self.lam = float(x1[0]), float(x1[1]), float(x1[2])
            self.sim_t += DT
            self.steps += 1
            _, aend = self._deriv(x1, *args)
            rec = self._record(inp, aend, AT, sp, req, cap, float(closure), foul, comp, dAT)
            self.buffer.append(rec)
            self.last_record = rec
            return rec

    def _record(self, inp, aend, AT, sp, req, cap, closure, foul, comp, dAT) -> dict:
        p = self.params
        r = aend["r"]
        P_e = float(aend["P_e"])
        values = {
            "AT": AT, "AP": inp["AP"], "AH": inp["AH"],
            "AFDP": float(r["AFDP"]), "GTEP": float(r["GTEP"]), "TIT": float(r["TIT"]), "TAT": float(r["TAT"]),
            "TEY": P_e,  # MW sustained for one hour == MWh per hourly-equivalent sample
            "CDP": float(r["CDP"]),
            "CO": float(ph.co(p, P_e / p["P_rated"])),
            "NOX": float(ph.nox(p, r["T3"], r["humidity_ratio"])),
        }
        phys_fault = foul > 0 or comp > 0 or dAT > 0
        prov = {k: ("real_input" if k in INPUT_CHANNELS else "simulated") for k in MEASUREMENT_KEYS}
        if phys_fault:
            for k in MEASUREMENT_KEYS:
                if k not in INPUT_CHANNELS:
                    prov[k] = "synthetic_fault"
            if dAT > 0:
                prov["AT"] = "synthetic_fault"
        for f in self.faults.values():
            if f["kind"] not in SENSOR_FAULTS:
                continue
            ch, mag = f["channel"], f["magnitude"]
            if f["kind"] == "sensor_bias":
                values[ch] += mag
            elif f["kind"] == "sensor_drift":
                values[ch] += mag * (self.sim_t - f["start_sim_t"]) / 3600.0
            elif f["kind"] == "sensor_spike":
                if f["_rng"].random() < 0.02:
                    values[ch] += mag
            elif f["kind"] == "sensor_stuck":
                if f["stuck_value"] is None:
                    f["stuck_value"] = values[ch]
                values[ch] = f["stuck_value"]
            prov[ch] = "synthetic_fault"
        return {
            "sim_time_s": self.sim_t,
            "source_year": self.year,
            "row_index": inp["row_index"],
            "channels": values,
            "provenance": prov,
            "synthetic": any(v == "synthetic_fault" for v in prov.values()),
            "active_fault_ids": sorted(self.faults),
            "energy_closure_pct": closure,
            "omega_pu": self.omega,
            "load_command": self.lam,
            "dispatch_requested_mw": req,
            "dispatch_setpoint_mw": sp,
            "dispatch_clipped": bool(req > sp + 1e-9),
            "available_capacity_mw": cap,
            "fuel_kg_s": float(r["m_fuel"]),
            "air_kg_s": float(r["m_air"]),
            "intake_fouling_factor": foul,
            "control": CONTROL_LABEL,
            "tey_note": "TEY = simulated electrical MW x 1 h (MWh per hourly-equivalent sample)",
        }

    def run_steps(self, n: int, setpoint_override: float | None = None) -> list[dict]:
        out = []
        for _ in range(int(n)):
            rec = self.step(setpoint_override)
            if rec is None:
                break
            out.append(rec)
        return out

    # ------------------------------------------------------------------ thread control
    def _loop(self) -> None:
        last = time.monotonic()
        frac = 0.0
        while not self._stop_evt.is_set():
            time.sleep(0.02)
            now = time.monotonic()
            with self.lock:
                if self.status != "running":
                    last = now
                    frac = 0.0
                    continue
                frac += self.speed * (now - last) / DT
                last = now
                n = min(int(frac), MAX_STEPS_PER_TICK)
                frac = min(frac - n, MAX_STEPS_PER_TICK)
                for _ in range(n):
                    if self.step() is None:
                        break

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._loop, name="thermomind-simulator", daemon=True)
            self._thread.start()

    def action(self, action: str, year=None, start_index=None, speed=None, rows_per_hour=None) -> dict:
        with self.lock:
            if action == "start":
                self.configure(year, start_index, speed, rows_per_hour)
                self._reset_state()
                self.buffer.clear()
                self._ensure_params()
                self.status = "running"
            elif action == "pause":
                if self.status == "running":
                    self.status = "paused"
            elif action == "resume":
                if self.status in ("paused", "stopped"):
                    self.status = "running"
            elif action == "stop":
                self.status = "stopped"
            elif action == "reset":
                self.status = "idle"
                self._reset_state()
                self.buffer.clear()
                self.faults.clear()
            elif action == "speed":
                if speed is None:
                    raise SimError("action 'speed' requires speed")
                self.speed = float(speed)
            else:
                raise SimError(f"unknown action '{action}'")
            running = self.status == "running"
        if running:
            self._ensure_thread()
        return self.state()

    def shutdown(self) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def state(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "acts_on": "software model only (SIMULATED_PLANT); no real plant is controlled",
                "simulated": True,
                "year": self.year,
                "start_index": self.start_index,
                "row_index": self.row_ptr(),
                "rows_per_hour": self.rows_per_hour,
                "speed": self.speed,
                "sim_time_s": self.sim_t,
                "steps": self.steps,
                "buffer_len": len(self.buffer),
                "buffer_max": BUFFER_MAX,
                "faults": [self._public_fault(f) for f in self.faults.values()],
                "last": self.last_record,
                "control": CONTROL_LABEL,
                "time_axis": "simulated seconds + replay source_year/row_index (no timestamps)",
            }

    def history(self, n: int) -> list[dict]:
        with self.lock:
            if n >= len(self.buffer):
                return list(self.buffer)
            return list(itertools.islice(self.buffer, len(self.buffer) - n, len(self.buffer)))


_engine: SimEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> SimEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SimEngine()
        return _engine
