"""Thermal models for the electrical balance of plant (planning/awareness models, NOT measurements).

All functions are pure and deterministic. Inputs are numpy arrays of the per-sample load ratio ``K`` (load /
rating, dimensionless) and an ambient temperature in °C. Each UCI row is an hourly aggregate, so transient
models step with ``dt_h = 1.0``.

Models (see docs/THERMAL_MONITORING.md for the full derivation and parameter table):

* Transformer top-oil / hot-spot — modelled after IEEE Std C57.91 (Guide for Loading Mineral-Oil-Immersed
  Transformers), Clause 7 "exponential" equations:
      Δθ_TO,U = Δθ_TO,R · ((K²·R + 1) / (R + 1))^n
      Δθ_H,U  = Δθ_H,R  · K^(2m)
      Δθ(t)   = Δθ_U + (Δθ_prev − Δθ_U) · exp(−Δt / τ)          (exact step for piecewise-constant load)
      θ_H     = θ_A + Δθ_TO + Δθ_H
* Insulation ageing — IEEE C57.91 Clause 5 (65 °C-rise thermally upgraded paper, 110 °C reference):
      F_AA = exp(15000/383 − 15000/(θ_H + 273)),   loss of life = Σ F_AA·Δt
* Conductors / busbar / switchgear contacts / generator stator — I²R heating at quasi-steady state:
      θ = θ_amb + Δθ_rated · K²
  with rated rises taken from typical type-test limits (IEC 62271-1 / IEEE C37.20.2 for switchgear,
  IEC 60034-1 class B rise for the stator) — confirm with equipment data.
* SYNTHETIC defect (T01_HOT_CONNECTION) — a single degrading connection whose rise coefficient grows
  linearly from 1× to (1+g)× over the window, plus seeded Gaussian jitter. Never on by default.
"""
from __future__ import annotations

import math

import numpy as np

AGEING_REF_HOT_SPOT_C = 110.0
AGEING_B = 15000.0
HOURS_PER_YEAR = 8760.0


def load_ratio(load: np.ndarray, rated: float) -> np.ndarray:
    """K = load / rated (both in MWh per hourly sample). Negative/NaN loads clamp to 0."""
    arr = np.nan_to_num(np.asarray(load, dtype=float), nan=0.0)
    return np.clip(arr, 0.0, None) / float(rated)


# ---------------------------------------------------------------------------
# Transformer (IEEE C57.91 Clause 7 style)
# ---------------------------------------------------------------------------


def top_oil_rise_ultimate(k, rise_rated: float, r: float, n: float) -> np.ndarray:
    k = np.asarray(k, dtype=float)
    return rise_rated * ((k * k * r + 1.0) / (r + 1.0)) ** n


def hot_spot_gradient_ultimate(k, gradient_rated: float, m: float) -> np.ndarray:
    k = np.asarray(k, dtype=float)
    return gradient_rated * np.power(k, 2.0 * m)


def transformer_steady_state(k: float, ambient_c: float, *, top_oil_rise_rated: float = 55.0,
                             hot_spot_gradient_rated: float = 25.0, r: float = 5.0, n: float = 0.8,
                             m: float = 0.8) -> tuple[float, float]:
    """Closed-form steady state (top_oil_c, hot_spot_c) for constant load ratio ``k``."""
    to = float(top_oil_rise_ultimate(k, top_oil_rise_rated, r, n))
    hs = float(hot_spot_gradient_ultimate(k, hot_spot_gradient_rated, m))
    return ambient_c + to, ambient_c + to + hs


def _first_order(ultimate: np.ndarray, tau_h: float, dt_h: float) -> np.ndarray:
    out = np.empty_like(ultimate)
    if ultimate.size == 0:
        return out
    a = math.exp(-dt_h / tau_h)
    out[0] = ultimate[0]  # initial condition: steady state at the first sample
    for i in range(1, ultimate.size):
        out[i] = ultimate[i] + (out[i - 1] - ultimate[i]) * a
    return out


def transformer_transient(k, ambient_c, *, top_oil_rise_rated: float = 55.0, hot_spot_gradient_rated: float = 25.0,
                          r: float = 5.0, n: float = 0.8, m: float = 0.8, tau_top_oil_h: float = 3.0,
                          tau_hot_spot_h: float = 0.1, dt_h: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Top-oil and hot-spot temperature series (°C) for a load-ratio series sampled every ``dt_h`` hours."""
    k = np.asarray(k, dtype=float)
    amb = np.asarray(ambient_c, dtype=float)
    d_to = _first_order(top_oil_rise_ultimate(k, top_oil_rise_rated, r, n), tau_top_oil_h, dt_h)
    d_h = _first_order(hot_spot_gradient_ultimate(k, hot_spot_gradient_rated, m), tau_hot_spot_h, dt_h)
    top_oil = amb + d_to
    return top_oil, top_oil + d_h


def ageing_acceleration_factor(hot_spot_c) -> np.ndarray:
    """F_AA = exp(15000/383 − 15000/(θ_H + 273)); equals 1.0 at θ_H = 110 °C."""
    hs = np.asarray(hot_spot_c, dtype=float)
    return np.exp(AGEING_B / (AGEING_REF_HOT_SPOT_C + 273.0) - AGEING_B / (hs + 273.0))


def cumulative_loss_of_life_h(hot_spot_c, dt_h: float = 1.0) -> np.ndarray:
    """Cumulative equivalent ageing hours Σ F_AA·Δt (IEEE C57.91 Clause 5)."""
    return np.cumsum(ageing_acceleration_factor(hot_spot_c) * dt_h)


# ---------------------------------------------------------------------------
# I²R assets (conductors, busbar, contacts, generator stator proxy)
# ---------------------------------------------------------------------------


def quadratic_rise_temperature(k, ambient_c, rated_rise_k: float) -> np.ndarray:
    """θ = θ_amb + Δθ_rated · K² (quasi-steady state at hourly resolution)."""
    k = np.asarray(k, dtype=float)
    return np.asarray(ambient_c, dtype=float) + rated_rise_k * k * k


def load_corrected_rise_index(temp_c, ambient_c, k, rated_rise_k: float, k_min: float = 0.2) -> np.ndarray:
    """(θ − θ_amb) / (Δθ_rated · K²): 1.0 for a healthy I²R element. Same load correction used for IR surveys
    (ΔT_corrected = ΔT_measured · (I_rated / I_measured)²). NaN where K < k_min (correction unreliable)."""
    k = np.asarray(k, dtype=float)
    denom = rated_rise_k * k * k
    out = (np.asarray(temp_c, dtype=float) - np.asarray(ambient_c, dtype=float)) / np.where(denom > 0, denom, np.nan)
    return np.where(k >= k_min, out, np.nan)


# ---------------------------------------------------------------------------
# SYNTHETIC defect + demand what-if
# ---------------------------------------------------------------------------


def inject_hot_connection(k, ambient_c, rated_rise_k: float, growth: float, seed: int,
                          jitter_k: float = 0.3) -> np.ndarray:
    """SYNTHETIC degrading connection: rise coefficient c(t) = 1 + g·t/(N−1), θ = θ_amb + c(t)·Δθ_rated·K² + ε,
    ε ~ N(0, jitter_k²) from ``numpy.random.default_rng(seed)``. Deterministic for a given seed."""
    k = np.asarray(k, dtype=float)
    n = k.size
    ramp = np.linspace(0.0, 1.0, n) if n > 1 else np.zeros(n)
    coeff = 1.0 + growth * ramp
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, jitter_k, n)
    return np.asarray(ambient_c, dtype=float) + coeff * rated_rise_k * k * k + noise


DIURNAL_AMPLITUDE = 0.25  # fraction of the added demand that swings over the notional day
DIURNAL_PEAK_HOUR = 15


def demand_multiplier_profile(row_index, multiplier: float, profile: str) -> np.ndarray:
    """Per-sample load multiplier for the what-if demand scenario.

    flat: m(t) = multiplier.
    diurnal_datacenter: added demand x = multiplier − 1 with a mild cooling-driven diurnal swing,
        m(t) = 1 + x·(1 + 0.25·cos(2π(h − 15)/24)), h = row_index mod 24 — a NOTIONAL hour, not a clock time
        (UCI rows have no timestamps). Mean over a full notional day equals ``multiplier``.
    """
    ri = np.asarray(row_index, dtype=float)
    if profile == "flat":
        return np.full(ri.shape, float(multiplier))
    if profile == "diurnal_datacenter":
        x = float(multiplier) - 1.0
        h = np.mod(ri, 24.0)
        return 1.0 + x * (1.0 + DIURNAL_AMPLITUDE * np.cos(2.0 * np.pi * (h - DIURNAL_PEAK_HOUR) / 24.0))
    raise ValueError(f"unknown demand_profile '{profile}' (expected flat or diurnal_datacenter)")
