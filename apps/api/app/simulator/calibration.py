"""Least-squares calibration of the simulated plant to real UCI rows (2011–2013), scored on 2014.

Method (all numbers come from running this code; nothing is hand-entered):
  1. Sample ~200 rows from 2011–2013 (fixed seed).
  2. For each row, use real AT/AP/AH and solve the load command λ so that the model's steady
     electrical output equals the real TEY (TEY in MWh per hourly sample ≈ mean MW).
  3. scipy.optimize.least_squares fits the physics parameters (PHYSICS_FIT_KEYS) minimising the
     std-normalised residuals of TIT, TAT, CDP, AFDP, GTEP (+ a penalty when λ leaves [0, 1]).
  4. With physics fixed, fit NOx (a, b) and CO (c, d) the same way.
  5. Score per-channel MAE on every 2014 row (held out).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from app import config
from app.simulator import physics as ph

FIT_YEARS = (2011, 2012, 2013)
TEST_YEAR = 2014
N_FIT_ROWS = 200
SEED = 551
PHYS_CHANNELS = ["TIT", "TAT", "CDP", "AFDP", "GTEP"]
LAM_GRID = np.linspace(-0.4, 1.4, 37)
_REPO_RAW = Path(__file__).resolve().parents[4] / "data" / "raw" / "uci_551"

_lock = threading.Lock()
_fit_lock = threading.Lock()
_frames: dict[int, pd.DataFrame] = {}
_report: dict | None = None
_params: dict | None = None


def raw_dir() -> Path:
    d = Path(config.RAW_UCI_DIR)
    if (d / f"gt_{TEST_YEAR}.csv").exists():
        return d
    return _REPO_RAW


def year_frame(year: int) -> pd.DataFrame:
    """Real UCI rows for one year (read-only, cached in memory). Raises KeyError if absent."""
    with _lock:
        if year not in _frames:
            path = raw_dir() / f"gt_{int(year)}.csv"
            if not path.exists():
                raise KeyError(f"UCI file for year {year} not available")
            _frames[year] = pd.read_csv(path)
        return _frames[year]


def solve_lambda(p: dict, AT, AP, AH, P_target, intake_fouling=0.0, comp_fouling=0.0, omega=1.0):
    """Per-row λ such that steady P_elec(λ) = P_target (grid evaluation + linear interpolation)."""
    AT, AP, AH, P_target = (np.atleast_1d(np.asarray(v, float)) for v in (AT, AP, AH, P_target))
    n = AT.size
    L = np.broadcast_to(LAM_GRID, (n, LAM_GRID.size))
    r = ph.plant(p, AT[:, None], AP[:, None], AH[:, None], L, omega, intake_fouling, comp_fouling)
    P = r["P_elec_ss"]
    lam = np.empty(n)
    for i in range(n):
        order = np.argsort(P[i])
        lam[i] = np.interp(P_target[i], P[i][order], LAM_GRID[order], left=LAM_GRID[0], right=LAM_GRID[-1])
    return lam


def predict(p: dict, df: pd.DataFrame) -> tuple[dict, np.ndarray]:
    lam = solve_lambda(p, df["AT"].to_numpy(), df["AP"].to_numpy(), df["AH"].to_numpy(), df["TEY"].to_numpy())
    r = ph.plant(p, df["AT"].to_numpy(), df["AP"].to_numpy(), df["AH"].to_numpy(), lam)
    r["NOX"] = ph.nox(p, r["T3"], r["humidity_ratio"])
    r["CO"] = ph.co(p, r["P_elec_ss"] / p["P_rated"])
    r["TEY"] = r["P_elec_ss"]
    return r, lam


def fit(n_rows: int = N_FIT_ROWS) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    fit_df = pd.concat([year_frame(y) for y in FIT_YEARS], ignore_index=True)
    sample = fit_df.sample(n=min(n_rows, len(fit_df)), random_state=SEED).reset_index(drop=True)
    stds = {c: float(fit_df[c].std()) for c in PHYS_CHANNELS}
    base = dict(ph.DEFAULT_PARAMS)
    x0 = np.array([base[k] for k in ph.PHYSICS_FIT_KEYS])
    lo = np.array([300, 8, 0.75, 0.80, 1150, 1300, 0.4, 50, 500, 0.0])
    hi = np.array([800, 20, 0.95, 0.95, 1350, 1500, 0.95, 2000, 8000, 10.0])

    def resid(x):
        p = dict(base, **dict(zip(ph.PHYSICS_FIT_KEYS, x)))
        if p["TIT_hi"] <= p["TIT_lo"] + 5:
            return np.full(len(sample) * (len(PHYS_CHANNELS) + 1), 50.0)
        r, lam = predict(p, sample)
        res = [(r[c] - sample[c].to_numpy()) / stds[c] for c in PHYS_CHANNELS]
        res.append(5.0 * (np.clip(lam - 1.0, 0, None) + np.clip(-lam, 0, None)))
        return np.concatenate(res)

    sol = least_squares(resid, x0, bounds=(lo, hi), x_scale=np.abs(x0), max_nfev=200)
    params = dict(base, **dict(zip(ph.PHYSICS_FIT_KEYS, map(float, sol.x))))

    r, _ = predict(params, sample)
    T3, wh, lf = r["T3"], r["humidity_ratio"], r["P_elec_ss"] / params["P_rated"]
    nox_y, co_y = sample["NOX"].to_numpy(), sample["CO"].to_numpy()

    def nres(x):
        return ph.nox(dict(params, nox_a=x[0], nox_b=x[1]), T3, wh) - nox_y

    def cres(x):
        return ph.co(dict(params, co_c=x[0], co_d=x[1]), lf) - co_y

    sn = least_squares(nres, [60.0, 0.0], bounds=([1e-3, -0.05], [1e4, 0.05]))
    sc = least_squares(cres, [1.0, 10.0], bounds=([0.0, 0.0], [100.0, 1e5]))
    params.update(nox_a=float(sn.x[0]), nox_b=float(sn.x[1]), co_c=float(sc.x[0]), co_d=float(sc.x[1]))

    test = year_frame(TEST_YEAR)
    rt, lam_t = predict(params, test)
    mae = {c: float(np.mean(np.abs(rt[c] - test[c].to_numpy()))) for c in PHYS_CHANNELS + ["NOX", "CO", "TEY"]}
    report = {
        "status": "calibrated",
        "method": "scipy.optimize.least_squares (physics: TIT/TAT/CDP/AFDP/GTEP std-normalised; then NOx a,b and CO c,d)",
        "fit_years": list(FIT_YEARS),
        "fit_rows": int(len(sample)),
        "fit_seed": SEED,
        "test_year": TEST_YEAR,
        "test_rows": int(len(test)),
        "per_channel_mae_test": mae,
        "test_channel_mean": {c: float(test[c].mean()) for c in mae},
        "fraction_test_rows_lambda_outside_0_1": float(np.mean((lam_t < 0) | (lam_t > 1))),
        "note": ("TEY MAE reflects only the λ-solve interpolation (TEY is the dispatch input in the fit). "
                 "Simplified 0-D simulator; MAEs are real values from this fit, not a validation of the plant."),
        "physics_cost": float(sol.cost),
        "params_at_bounds": [k for k, v, l, h in zip(ph.PHYSICS_FIT_KEYS, sol.x, lo, hi)
                             if v <= l * 1.0001 or v >= h * 0.9999],
        "params": params,
        "fit_seconds": round(time.perf_counter() - t0, 2),
        "synthetic": False,
        "provenance_kind": "model_derived",
    }
    return params, report


def uncalibrated_report(reason: str) -> dict:
    return {"status": "uncalibrated", "reason": reason, "params": dict(ph.DEFAULT_PARAMS),
            "per_channel_mae_test": {}, "provenance_kind": "model_derived", "synthetic": False}


def get_calibration() -> tuple[dict, dict]:
    """Cached (params, report). Falls back to documented defaults (status 'uncalibrated') if UCI files are absent."""
    global _report, _params
    with _fit_lock:
        if _params is None:
            try:
                _params, _report = fit()
            except KeyError as exc:
                _params, _report = dict(ph.DEFAULT_PARAMS), uncalibrated_report(str(exc))
        return dict(_params), dict(_report)
