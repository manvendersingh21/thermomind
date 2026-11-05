"""0-D (lumped) physics model of a single-shaft heavy-duty gas turbine — SIMULATED PLANT.

This is a software model only. It controls nothing real. Every quantity is SI internally
(K, Pa, kg/s, J/kg, W -> reported in MW) and converted to the UCI published channel units
only when reported. Equations (stations: 1 compressor inlet, 2 compressor exit,
3 turbine inlet, 4 turbine exit):

Working-fluid properties (air and combustion gas treated alike — documented simplification):
    cp(T)  = 1005 + 0.1·(T − 300)                       [J/(kg·K)]
    h(T)   = ∫_300^T cp dT = 1005·x + 0.05·x²,  x = T − 300   [J/kg]
    s°(T)  = ∫ cp/T dT = 975·ln T + 0.1·T               (entropy function)
    isentropic:  s°(T_s) − s°(T_in) = R·ln(p_out/p_in),  R = 287 J/(kg·K)  (Newton solve)

Intake filter:   ΔP_f = k_f·(ṁ/ṁ_ref)²·(1 + fouling)    → AFDP [mbar]
                 p1 = p_amb − ΔP_f,  T1 = AT + 273.15
Compressor map (simple):
    N_c   = ω·sqrt(288.15/T1)                         corrected speed
    ṁ_c   = φ(λ)·N_c·ṁ_ref·(1 − 0.5·comp_foul)         corrected flow (φ = IGV flow fraction)
    ṁ     = ṁ_c·(p1/101325)/sqrt(T1/288.15)
    PR    = 1 + (PR_ref − 1)·(ṁ_c/ṁ_ref)·N_c
    η_c   = η_c,ref·(1 − comp_foul)
    h2    = h1 + (h2s − h1)/η_c,  W_c = ṁ·(h2 − h1),  p2 = PR·p1
    CDP   reported = p2/1e5 (numerically bar absolute). The UCI file labels CDP "mbar"; its
          values (~10–15) only make sense as bar, so we report in the published *numeric*
          convention and keep the unit flag "as published; unit under validation".
Combustor (energy balance, LHV = 47 MJ/kg, fuel enters at 300 K, η_b = 0.995):
    η_b·ṁ_f·LHV = (ṁ + ṁ_f)·h3 − ṁ·h2   →   ṁ_f = ṁ·(h3 − h2)/(η_b·LHV − h3)
    T3 = TIT target from the load command λ:  T3 = TIT_lo + (TIT_hi − TIT_lo)·λ
    p3 = (1 − 0.04)·p2   (4 % combustor pressure loss)
Exhaust / turbine:
    ΔP_ex = k_ex·(ṁ_g/ṁ_ref)²  → GTEP [mbar],  p4 = p_amb + ΔP_ex
    h4 = h3 − η_t·(h3 − h4s),  W_t = ṁ_g·(h3 − h4),  TAT = T4 − 273.15
Shaft / generator:
    P_m = W_t − W_c − P_loss;  P_e(steady) = η_g·P_m;  TEY = P_e[MW]·1 h  [MWh per hourly-equivalent sample]
Emissions (empirical, constants fitted to 2011–2013 UCI rows):
    T_flame ≈ T3 + 150 K (fixed primary-zone offset)
    NOx = a·exp(b·(T_flame − T_ref))·exp(−19·(w − 0.00634))   (w = humidity ratio, standard correction)
    CO  = c·(1 + d·(1 − load_fraction)²)
"""
from __future__ import annotations

import math

import numpy as np


def _f(fn_math, fn_np):
    """Use fast ``math`` on Python floats (dynamic RK4 path), numpy on arrays (calibration path)."""
    def g(x):
        return fn_math(x) if isinstance(x, float) else fn_np(x)
    return g


_exp, _log, _sqrt = _f(math.exp, np.exp), _f(math.log, np.log), _f(math.sqrt, np.sqrt)


def _clip(x, lo, hi):
    return min(max(x, lo), hi) if isinstance(x, float) else np.clip(x, lo, hi)


R_AIR = 287.0
LHV = 47.0e6
ETA_B = 0.995
COMB_DP = 0.04
P_ISO = 101325.0
T_ISO = 288.15
T_REF_NOX = 1600.0
FLAME_OFFSET = 150.0

DEFAULT_PARAMS: dict[str, float] = {
    "m_ref": 500.0,      # kg/s full-IGV ISO corrected air flow
    "PR_ref": 13.0,      # pressure ratio at ṁ_c = ṁ_ref, N_c = 1
    "eta_c": 0.88,
    "eta_t": 0.90,
    "TIT_lo": 1270.0,    # K at λ = 0
    "TIT_hi": 1375.0,    # K at λ = 1
    "phi_lo": 0.70,      # IGV flow fraction at λ = 0
    "k_f": 450.0,        # Pa filter ΔP at ṁ_ref, clean
    "k_ex": 3000.0,      # Pa exhaust ΔP at ṁ_ref
    "P_loss": 2.0,       # MW mechanical/auxiliary losses
    "eta_g": 0.985,
    "P_rated": 180.0,    # MW, per-unit base for the swing equation
    "nox_a": 60.0, "nox_b": 0.0,
    "co_c": 1.0, "co_d": 10.0,
}
PHYSICS_FIT_KEYS = ["m_ref", "PR_ref", "eta_c", "eta_t", "TIT_lo", "TIT_hi", "phi_lo", "k_f", "k_ex", "P_loss"]


def cp(T):
    return 1005.0 + 0.1 * (T - 300.0)


def enthalpy(T):
    x = T - 300.0
    return 1005.0 * x + 0.05 * x * x


def temp_from_h(h):
    return 300.0 + (-1005.0 + _sqrt(1005.0 ** 2 + 0.2 * h)) / 0.1


def _s0(T):
    return 975.0 * _log(T) + 0.1 * T


def isentropic_T(T_in, pressure_ratio_out_in):
    """T_s with s°(T_s) − s°(T_in) = R·ln(p_out/p_in) (Newton, 4 iterations, exact for cp(T))."""
    target = _s0(T_in) + R_AIR * _log(pressure_ratio_out_in)
    T = T_in * pressure_ratio_out_in ** (R_AIR / cp(T_in))
    for _ in range(4):
        T = T - (_s0(T) - target) / (975.0 / T + 0.1)
    return T


def humidity_ratio(T_C, p_pa, rh_pct):
    """kg water / kg dry air from relative humidity (Magnus saturation pressure)."""
    p_sat = 610.94 * _exp(17.625 * T_C / (T_C + 243.04))
    p_v = _clip(rh_pct, 0.0, 100.0) / 100.0 * p_sat
    return 0.622 * p_v / (p_pa - p_v)


def plant(p: dict, AT, AP_mbar, AH, lam, omega=1.0, intake_fouling=0.0, comp_fouling=0.0) -> dict:
    """Algebraic (quasi-steady) thermodynamic cycle for load command ``lam``. Vectorised over numpy arrays."""
    if not isinstance(AT, float):
        AT = np.asarray(AT, dtype=float)
        lam = np.asarray(lam, dtype=float)
    T1 = AT + 273.15
    p_amb = AP_mbar * 100.0
    phi = p["phi_lo"] + (1.0 - p["phi_lo"]) * lam
    Nc = omega * _sqrt(T_ISO / T1)
    mc = phi * Nc * p["m_ref"] * (1.0 - 0.5 * comp_fouling)
    # filter ΔP depends on ṁ, which depends on p1: two fixed-point passes are ample (ΔP ≪ p_amb)
    p1 = p_amb
    for _ in range(2):
        m = mc * (p1 / P_ISO) / _sqrt(T1 / T_ISO)
        dp_f = p["k_f"] * (m / p["m_ref"]) ** 2 * (1.0 + intake_fouling)
        p1 = p_amb - dp_f
    m = mc * (p1 / P_ISO) / _sqrt(T1 / T_ISO)
    PR = 1.0 + (p["PR_ref"] - 1.0) * (mc / p["m_ref"]) * Nc
    eta_c = p["eta_c"] * (1.0 - comp_fouling)
    h1 = enthalpy(T1)
    h2 = h1 + (enthalpy(isentropic_T(T1, PR)) - h1) / eta_c
    T2 = temp_from_h(h2)
    W_c = m * (h2 - h1)
    p2 = PR * p1
    T3 = p["TIT_lo"] + (p["TIT_hi"] - p["TIT_lo"]) * lam
    h3 = enthalpy(T3)
    m_f = m * (h3 - h2) / (ETA_B * LHV - h3)
    m_g = m + m_f
    p3 = (1.0 - COMB_DP) * p2
    dp_ex = p["k_ex"] * (m_g / p["m_ref"]) ** 2
    p4 = p_amb + dp_ex
    h4 = h3 - p["eta_t"] * (h3 - enthalpy(isentropic_T(T3, p4 / p3)))
    T4 = temp_from_h(h4)
    W_t = m_g * (h3 - h4)
    P_m = (W_t - W_c) / 1e6 - p["P_loss"]
    w_h = humidity_ratio(AT, p_amb, AH)
    return {
        "T1": T1, "p1": p1, "m_air": m, "PR": PR, "T2": T2, "p2": p2, "W_c": W_c / 1e6, "h1": h1, "h2": h2,
        "T3": T3, "m_fuel": m_f, "m_gas": m_g, "p4": p4, "T4": T4, "h4": h4, "W_t": W_t / 1e6,
        "P_mech": P_m, "P_elec_ss": p["eta_g"] * P_m,
        "AFDP": dp_f / 100.0, "GTEP": dp_ex / 100.0, "CDP": p2 / 1e5,
        "TIT": T3 - 273.15, "TAT": T4 - 273.15, "humidity_ratio": w_h,
    }


def nox(p, T3, w_h):
    return p["nox_a"] * _exp(p["nox_b"] * (T3 + FLAME_OFFSET - T_REF_NOX)) * _exp(-19.0 * (w_h - 0.00634))


def co(p, load_fraction):
    return p["co_c"] * (1.0 + p["co_d"] * (1.0 - _clip(load_fraction, 0.0, 1.5)) ** 2)
