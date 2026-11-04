"""Deterministic maintenance-planning computations (compressor wash, inlet filter change-out).

Pure functions (``compute_compressor_wash``, ``compute_filter_changeout``, ``estimate_afdp_proxy``) take
frames/arrays and request objects so they can be tested on synthetic data; ``run_*`` functions wire
them to the dataset repository and the production baseline model.

Honesty rules applied here:
- UCI rows have no timestamps: positions are ``row_index`` within ``source_year`` (one row = one hourly sample).
- TEY is MWh per hourly sample as published; nothing is converted to MW.
- Every economic input is echoed back as an assumption; outputs are planning aids for human review and
  never claim avoided downtime or prescribe an action.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.features.planner.schemas import (
    AfdpProxy,
    Assumption,
    CdpTrend,
    CompressorWashRequest,
    CompressorWashResult,
    FilterChangeoutRequest,
    FilterChangeoutResult,
    FilterSeriesPoint,
    PlannerOptions,
    ProjectionPoint,
    WashSeriesPoint,
)

FEATURES = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP"]
MAX_SERIES_POINTS = 400
BEST_PERCENTILE = 95.0
CLEAN_PERCENTILE = 5.0
MIN_PROXY_ROWS = 500
PROJECTION_HORIZON_SAMPLES = 17_520  # ~2 years of hourly samples; beyond that a straight-line projection is meaningless
SENSITIVITY_STEP_MBAR = 0.5
SENSITIVITY_MAX_ROWS = 5000


class ModelMissingError(RuntimeError):
    """Raised when the production baseline model is not available (API -> 404)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _f(x: Any) -> Optional[float]:
    """Plain float rounded for transport, None when not finite."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, 6) if math.isfinite(v) else None


def rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing (causal) rolling median; needs at least half a window of finite values."""
    s = pd.Series(np.asarray(values, dtype=float))
    return s.rolling(window, min_periods=max(2, window // 2)).median().to_numpy(dtype=float)


def downsample_positions(n: int, max_points: int = MAX_SERIES_POINTS) -> np.ndarray:
    """Deterministic stride sampling that always keeps the first and last position."""
    if n <= 0:
        return np.array([], dtype=int)
    stride = max(1, math.ceil(n / max_points))
    return np.unique(np.r_[np.arange(0, n, stride), n - 1]).astype(int)


def _assumptions(req: Any, spec: list[tuple[str, str, str]]) -> list[Assumption]:
    fields_set = getattr(req, "model_fields_set", set())
    out = []
    for key, label, unit in spec:
        out.append(
            Assumption(
                key=key,
                label=label,
                value=getattr(req, key),
                unit=unit,
                source="user_input" if key in fields_set else "default",
            )
        )
    return out


_COMMON_SPEC = [
    ("dataset_id", "Dataset", "id"),
    ("year", "Source year analysed", "year"),
    ("rolling_window_samples", "Rolling-median window", "hourly samples"),
    ("energy_price_per_mwh", "Energy price", "currency / MWh"),
]
WASH_SPEC = _COMMON_SPEC + [
    ("wash_outage_hours", "Offline wash outage", "hours"),
    ("wash_direct_cost", "Wash direct cost", "currency"),
    ("expected_recovery_fraction", "Expected recovery of lost output by a wash", "fraction 0–1"),
]
FILTER_SPEC = _COMMON_SPEC + [
    ("afdp_limit_mbar", "AFDP change-out limit", "mbar"),
    ("trend_window_samples", "Trailing samples used for the linear AFDP trend", "hourly samples"),
    ("filter_change_cost", "Filter change-out cost", "currency"),
    ("filter_outage_hours", "Filter change-out outage", "hours"),
]


def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2 or np.ptp(x[mask]) == 0:
        return None
    slope, intercept = np.polyfit(x[mask].astype(float), y[mask].astype(float), 1)
    return float(slope), float(intercept)


def _first_crossing(values: np.ndarray, threshold: float, start_pos: int, stop_pos: int) -> Optional[int]:
    """First position p in (start_pos, stop_pos] with values[p] >= threshold."""
    if stop_pos <= start_pos:
        return None
    seg = values[start_pos + 1 : stop_pos + 1]
    hits = np.nonzero(seg >= threshold)[0]
    return int(start_pos + 1 + hits[0]) if hits.size else None


def _typical_output(frame: pd.DataFrame) -> Optional[float]:
    if "TEY" not in frame.columns:
        return None
    tey = frame["TEY"].to_numpy(dtype=float)
    tey = tey[np.isfinite(tey)]
    return float(np.median(tey)) if tey.size else None


# ---------------------------------------------------------------------------
# 1. Compressor fouling / offline water wash
# ---------------------------------------------------------------------------

WASH_CAVEATS = [
    "The residual (observed − expected TEY) is model-derived. Shifts in it can come from fouling, but also from "
    "model drift, sensor drift, or operating regimes not seen in training; the UCI data has no verified wash or fault labels.",
    "Recoverable output is estimated as the gap to the year's p95 rolling residual — an optimistic reference, not a measured clean-engine level.",
    "No dates exist in the UCI data; positions are hourly sample indices within the year.",
    "Outage cost assumes the unit would otherwise run at the year's median TEY for every outage hour.",
    "This is a planning aid; it does not estimate or claim avoided downtime and is not a maintenance instruction.",
]


def _wash_insufficient(req: CompressorWashRequest, n: int, model_version: Optional[str], reason: str) -> CompressorWashResult:
    return CompressorWashResult(
        dataset_id=req.dataset_id,
        year=req.year,
        model_version=model_version,
        n_samples=n,
        rolling_window_samples=req.rolling_window_samples,
        status="insufficient data",
        status_reasons=[reason],
        computation=f"Not computed: {reason}",
        assumptions=_assumptions(req, WASH_SPEC),
        caveats=list(WASH_CAVEATS),
    )


def compute_compressor_wash(
    frame: pd.DataFrame,
    residuals: np.ndarray,
    req: CompressorWashRequest,
    model_version: Optional[str] = None,
    validation_residual_std: Optional[float] = None,
) -> CompressorWashResult:
    """Cumulative-loss-vs-wash-cost break-even on the rolling median of the TEY residual."""
    n = len(frame)
    w = int(req.rolling_window_samples)
    res = np.asarray(residuals, dtype=float)
    if res.shape[0] != n:
        raise ValueError("residuals length does not match frame length")
    rows = frame["row_index"].to_numpy(dtype=int) if "row_index" in frame.columns else np.arange(n)

    n_finite = int(np.isfinite(res).sum())
    if n_finite < 2 * w:
        return _wash_insufficient(
            req, n, model_version,
            f"{n_finite} finite residuals in {req.year}; need at least 2 × rolling window = {2 * w}.",
        )
    roll = rolling_median(res, w)
    valid = np.isfinite(roll)
    if int(valid.sum()) < w:
        return _wash_insufficient(req, n, model_version, f"only {int(valid.sum())} rolling values; need {w}.")

    best = float(np.percentile(roll[valid], BEST_PERCENTILE))
    valid_pos = np.nonzero(valid)[0]
    cur_pos = int(valid_pos[-1])
    current = float(roll[cur_pos])
    best_pos = int(np.nonzero(valid & (roll >= best))[0][-1])  # most recent sample at/above the best level

    gap = np.where(valid, np.clip(best - roll, 0.0, None), 0.0)
    gap[: best_pos + 1] = 0.0
    cum = np.cumsum(gap)  # MWh: each sample is one hour
    cum_total = float(cum[cur_pos])
    rate_now = max(0.0, best - current)

    price = float(req.energy_price_per_mwh)
    rec = float(req.expected_recovery_fraction)
    typical = _typical_output(frame)
    outage_mwh = float(req.wash_outage_hours) * (typical or 0.0)
    outage_value = outage_mwh * price
    total_cost = float(req.wash_direct_cost) + outage_value
    recoverable_value = rec * cum_total * price

    be_pos: Optional[int] = None
    if rec * price > 0:
        threshold_mwh = total_cost / (rec * price)
        be_pos = _first_crossing(np.where(cum > 0, cum, -np.inf), threshold_mwh, best_pos, cur_pos)
    break_even = be_pos is not None
    payback = (total_cost / (rec * rate_now * price)) if rate_now > 0 and price > 0 else None

    reasons: list[str] = []
    if break_even and rate_now > 0:
        status = "consider scheduling a wash (human decision)"
        reasons.append(
            f"Recoverable value of cumulative lost output ({recoverable_value:,.0f}) reached the wash cost "
            f"({total_cost:,.0f}) at {req.year} • sample #{int(rows[be_pos])}, and output is still below the best level now."
        )
    else:
        status = "no economic case yet"
        if rate_now <= 0:
            reasons.append("Current rolling residual is at or above the year's best (p95) level — no recoverable gap now.")
        if not break_even:
            reasons.append(
                f"Recoverable value of cumulative lost output ({recoverable_value:,.0f}) is below the wash cost ({total_cost:,.0f})."
            )
        else:
            reasons.append(
                f"Break-even was reached at sample #{int(rows[be_pos])}, but output has since returned to the best level."
            )

    # CDP context (not used in economics)
    cdp = CdpTrend()
    if "CDP" in frame.columns:
        cdp_roll = rolling_median(frame["CDP"].to_numpy(dtype=float), w)
        cv = np.nonzero(np.isfinite(cdp_roll))[0]
        if cv.size >= 2:
            fit = _linear_fit(cv.astype(float), cdp_roll[cv])
            cdp = CdpTrend(
                start_rolling=_f(cdp_roll[cv[0]]),
                end_rolling=_f(cdp_roll[cv[-1]]),
                slope_per_1000_samples=_f(fit[0] * 1000.0) if fit else None,
            )

    series: list[WashSeriesPoint] = []
    cdp_roll_all = rolling_median(frame["CDP"].to_numpy(dtype=float), w) if "CDP" in frame.columns else None
    for p in downsample_positions(n):
        series.append(
            WashSeriesPoint(
                row_index=int(rows[p]),
                rolling_residual_mwh=_f(roll[p]),
                cumulative_loss_mwh=_f(cum[p]) if best_pos <= p <= cur_pos else None,
                cdp_rolling=_f(cdp_roll_all[p]) if cdp_roll_all is not None else None,
            )
        )

    computation = (
        f"Residual = observed TEY − expected TEY (production baseline {model_version or 'n/a'}) for {n} hourly samples of {req.year}. "
        f"Trailing {w}-sample rolling median → best level = p{BEST_PERCENTILE:.0f} of the rolling residual = {best:.3f} MWh/sample, "
        f"last reached at sample #{int(rows[best_pos])}. Current rolling residual (sample #{int(rows[cur_pos])}) = {current:.3f} MWh/sample, "
        f"so lost-output rate now = max(0, {best:.3f} − {current:.3f}) = {rate_now:.3f} MWh per hourly sample. "
        f"Cumulative lost output since sample #{int(rows[best_pos])} = Σ max(0, best − rolling) × 1 h = {cum_total:.1f} MWh. "
        f"Wash cost = direct {req.wash_direct_cost:,.0f} + outage {req.wash_outage_hours:g} h × median TEY {typical or 0:.2f} MWh/sample × "
        f"price {price:g} = {total_cost:,.0f}. Recoverable value = recovery {rec:g} × {cum_total:.1f} MWh × {price:g} = {recoverable_value:,.0f}. "
        f"Break-even when recoverable value ≥ wash cost: "
        + (f"reached at sample #{int(rows[be_pos])}." if break_even else "not reached in this year.")
        + (
            f" If the current loss rate persisted, a wash would pay back in ≈ {payback:,.0f} h."
            if payback is not None
            else ""
        )
    )

    caveats = list(WASH_CAVEATS)
    med_res = float(np.nanmedian(res))
    offset_note = f"Median residual over {req.year} = {med_res:+.3f} MWh/sample"
    if validation_residual_std:
        offset_note += f" (baseline validation residual std = {validation_residual_std:.3f})"
    offset_note += "; a year-level offset can reflect model or regime drift as well as fouling."
    caveats.insert(1, offset_note)

    return CompressorWashResult(
        dataset_id=req.dataset_id,
        year=req.year,
        model_version=model_version,
        n_samples=n,
        rolling_window_samples=w,
        current_index=int(rows[cur_pos]),
        status=status,
        status_reasons=reasons,
        best_rolling_residual_mwh=_f(best),
        best_index=int(rows[best_pos]),
        current_rolling_residual_mwh=_f(current),
        lost_output_rate_now_mwh_per_sample=_f(rate_now),
        cumulative_lost_output_mwh=_f(cum_total),
        typical_output_mwh_per_sample=_f(typical),
        economics={
            "energy_price_per_mwh": _f(price),
            "loss_value_rate_now_per_hour": _f(rate_now * price),
            "outage_lost_output_mwh": _f(outage_mwh),
            "outage_lost_output_value": _f(outage_value),
            "direct_cost": _f(req.wash_direct_cost),
            "total_cost": _f(total_cost),
            "cumulative_loss_value": _f(cum_total * price),
            "recoverable_value": _f(recoverable_value),
        },
        break_even_reached=break_even,
        break_even_index=int(rows[be_pos]) if be_pos is not None else None,
        payback_hours_if_rate_persists=_f(payback),
        cdp=cdp,
        series=series,
        computation=computation,
        assumptions=_assumptions(req, WASH_SPEC),
        caveats=caveats,
    )


# ---------------------------------------------------------------------------
# 2. Inlet filter change-out
# ---------------------------------------------------------------------------

PROXY_STATEMENT = "Statistical association in this plant's data, not physics."


def estimate_afdp_proxy(train_frame: pd.DataFrame, model: Any = None, training_years: list[int] | None = None) -> AfdpProxy:
    """Output penalty per mbar of AFDP, estimated from the training years.

    Primary: AFDP coefficient of an ordinary-least-squares fit TEY ~ all 8 model features + intercept (partial
    association, holding the other measured variables fixed). Cross-checks: slope of the baseline residual on AFDP
    (≈0 by construction because AFDP is a model input) and the baseline model's finite-difference sensitivity.
    """
    years = list(training_years or [])
    cols = FEATURES + ["TEY"]
    if any(c not in train_frame.columns for c in cols):
        return AfdpProxy(method="unavailable", training_years=years, notes=["training frame lacks required columns"])
    tf = train_frame[cols].astype(float)
    tf = tf[np.isfinite(tf.to_numpy()).all(axis=1)]
    if len(tf) < MIN_PROXY_ROWS:
        return AfdpProxy(
            method="unavailable",
            training_years=years,
            n_rows=len(tf),
            notes=[f"only {len(tf)} complete training rows; need {MIN_PROXY_ROWS}"],
        )
    X = np.column_stack([tf[c].to_numpy() for c in FEATURES] + [np.ones(len(tf))])
    coef, *_ = np.linalg.lstsq(X, tf["TEY"].to_numpy(), rcond=None)
    ols = float(coef[FEATURES.index("AFDP")])

    resid_slope = None
    sens = None
    notes = [
        "Primary coefficient: OLS of TEY on AT, AP, AH, AFDP, GTEP, TIT, TAT, CDP (+ intercept) over the training years; "
        "AFDP coefficient used as MWh per hourly sample per mbar.",
        "A raw TEY–AFDP correlation is confounded by load (more air flow → higher ΔP and more output), so it is not used.",
    ]
    if model is not None:
        try:
            r = np.asarray(model.residuals(tf), dtype=float)
            fit = _linear_fit(tf["AFDP"].to_numpy(), r)
            resid_slope = fit[0] if fit else None
            stride = max(1, math.ceil(len(tf) / SENSITIVITY_MAX_ROWS))
            sub = tf.iloc[::stride]
            bumped = sub.copy()
            bumped["AFDP"] = bumped["AFDP"] + SENSITIVITY_STEP_MBAR
            sens = float(np.nanmean(model.predict(bumped) - model.predict(sub)) / SENSITIVITY_STEP_MBAR)
            notes.append(
                "Cross-check: residual-vs-AFDP slope is near zero by construction (AFDP is a model input); "
                f"baseline model finite-difference sensitivity (+{SENSITIVITY_STEP_MBAR} mbar, every {stride}th training row)."
            )
        except Exception as exc:  # noqa: BLE001 - cross-checks are optional
            notes.append(f"model cross-check unavailable ({type(exc).__name__})")
    return AfdpProxy(
        method="ols_partial_coefficient_training_years",
        coefficient_mwh_per_sample_per_mbar=_f(ols),
        residual_slope_mwh_per_mbar=_f(resid_slope),
        model_sensitivity_mwh_per_mbar=_f(sens),
        training_years=years,
        n_rows=int(len(tf)),
        statement=PROXY_STATEMENT,
        notes=notes,
    )


FILTER_CAVEATS = [
    "The output penalty per mbar is a statistical association in this plant's data, not physics; it may be confounded.",
    "Assumes a change-out returns AFDP to the year's clean level (p5 of the rolling median) and recovers the associated output fully.",
    "The linear trend is fitted to a trailing window of the rolling median; filter loading is often non-linear and "
    "step changes (earlier change-outs, washes, seasons) break straight-line extrapolation.",
    "No dates exist in the UCI data; 'hours to limit' assumes one hourly sample per operating hour.",
    "This is a planning aid; it does not estimate or claim avoided downtime and is not a maintenance instruction.",
]


def _filter_insufficient(
    req: FilterChangeoutRequest, n: int, model_version: Optional[str], proxy: AfdpProxy,
    afdp_range: Optional[list[float]], reason: str,
) -> FilterChangeoutResult:
    return FilterChangeoutResult(
        dataset_id=req.dataset_id,
        year=req.year,
        model_version=model_version,
        n_samples=n,
        rolling_window_samples=req.rolling_window_samples,
        trend_window_samples=req.trend_window_samples,
        afdp_limit_mbar=req.afdp_limit_mbar,
        afdp_training_range_mbar=afdp_range,
        status="insufficient data",
        status_reasons=[reason],
        proxy=proxy,
        computation=f"Not computed: {reason}",
        assumptions=_assumptions(req, FILTER_SPEC),
        caveats=list(FILTER_CAVEATS),
    )


def compute_filter_changeout(
    frame: pd.DataFrame,
    req: FilterChangeoutRequest,
    proxy: AfdpProxy,
    model_version: Optional[str] = None,
    afdp_training_range: Optional[list[float]] = None,
) -> FilterChangeoutResult:
    n = len(frame)
    w = int(req.rolling_window_samples)
    tw = int(req.trend_window_samples)
    rng = [float(v) for v in afdp_training_range] if afdp_training_range else None
    if "AFDP" not in frame.columns:
        return _filter_insufficient(req, n, model_version, proxy, rng, "AFDP column missing.")
    rows = frame["row_index"].to_numpy(dtype=int) if "row_index" in frame.columns else np.arange(n)
    afdp = frame["AFDP"].to_numpy(dtype=float)
    n_finite = int(np.isfinite(afdp).sum())
    if n_finite < 2 * w:
        return _filter_insufficient(
            req, n, model_version, proxy, rng,
            f"{n_finite} finite AFDP samples in {req.year}; need at least 2 × rolling window = {2 * w}.",
        )
    roll = rolling_median(afdp, w)
    valid = np.isfinite(roll)
    valid_pos = np.nonzero(valid)[0]
    cur_pos = int(valid_pos[-1])
    fit_lo = max(0, cur_pos - tw + 1)
    fit_mask = valid.copy()
    fit_mask[:fit_lo] = False
    if int(fit_mask.sum()) < 24:
        return _filter_insufficient(
            req, n, model_version, proxy, rng,
            f"only {int(fit_mask.sum())} rolling AFDP values in the trailing {tw}-sample trend window; need 24.",
        )
    pos_all = np.arange(n, dtype=float)
    fit = _linear_fit(pos_all[fit_mask], roll[fit_mask])
    slope, intercept = fit if fit else (0.0, float(np.nanmedian(roll[fit_mask])))
    fitted_now = slope * cur_pos + intercept
    current = float(roll[cur_pos])
    limit = float(req.afdp_limit_mbar)

    limit_reached = current >= limit
    samples_to_limit: Optional[float]
    proj_idx: Optional[int] = None
    horizon_note = None
    if limit_reached:
        samples_to_limit = 0.0
        proj_idx = int(rows[cur_pos])
    elif slope > 0:
        samples_to_limit = max(0.0, (limit - fitted_now) / slope)
        if samples_to_limit <= PROJECTION_HORIZON_SAMPLES:
            proj_idx = int(rows[cur_pos]) + int(math.ceil(samples_to_limit))
        else:
            horizon_note = (
                f"Straight-line projection reaches the limit only after {samples_to_limit:,.0f} samples "
                f"(> {PROJECTION_HORIZON_SAMPLES:,}); treated as beyond the planning horizon."
            )
    else:
        samples_to_limit = None
        horizon_note = "AFDP trend over the trailing window is flat or falling; no projected limit crossing."

    # projection line (2 points: linear) from the last sample forward
    if proj_idx is not None and not limit_reached:
        end_row = proj_idx
    else:
        end_row = int(rows[cur_pos]) + tw
    end_pos = cur_pos + (end_row - int(rows[cur_pos]))
    projection = [
        ProjectionPoint(row_index=int(rows[cur_pos]), trend_mbar=round(fitted_now, 6)),
        ProjectionPoint(row_index=int(end_row), trend_mbar=round(slope * end_pos + intercept, 6)),
    ]

    # economics via the proxy
    clean = float(np.percentile(roll[valid], CLEAN_PERCENTILE))
    clean_candidates = np.nonzero(valid & (roll <= clean))[0]
    clean_candidates = clean_candidates[clean_candidates <= cur_pos]
    clean_pos = int(clean_candidates[-1]) if clean_candidates.size else int(valid_pos[0])
    coef = proxy.coefficient_mwh_per_sample_per_mbar
    penalty = max(0.0, -float(coef)) if coef is not None else None
    price = float(req.energy_price_per_mwh)
    typical = _typical_output(frame)
    outage_mwh = float(req.filter_outage_hours) * (typical or 0.0)
    total_cost = float(req.filter_change_cost) + outage_mwh * price

    loss = np.zeros(n)
    rate_now = None
    cum_total = None
    be_pos = None
    payback = None
    if penalty is not None:
        loss = np.where(valid, penalty * np.clip(roll - clean, 0.0, None), 0.0)
        loss[: clean_pos + 1] = 0.0
        cum = np.cumsum(loss)
        cum_total = float(cum[cur_pos])
        rate_now = penalty * max(0.0, current - clean)
        if price > 0:
            be_pos = _first_crossing(np.where(cum > 0, cum, -np.inf), total_cost / price, clean_pos, cur_pos)
            payback = total_cost / (rate_now * price) if rate_now > 0 else None
    else:
        cum = np.full(n, np.nan)
    break_even = be_pos is not None

    reasons: list[str] = []
    if limit_reached:
        reasons.append(f"Rolling AFDP {current:.2f} mbar is at or above your limit {limit:g} mbar.")
    if break_even and (rate_now or 0) > 0:
        reasons.append(
            f"Value of cumulative output associated with elevated AFDP reached the change-out cost ({total_cost:,.0f}) "
            f"at {req.year} • sample #{int(rows[be_pos])}."
        )
    if limit_reached or (break_even and (rate_now or 0) > 0):
        status = "consider scheduling a filter change-out (human decision)"
    else:
        status = "no economic case yet"
        if penalty is None:
            reasons.append("Output-penalty proxy unavailable (not enough training rows); limit projection only.")
        elif penalty == 0:
            reasons.append("Training-data association between AFDP and output is not negative; no output penalty is attributed.")
        else:
            reasons.append(
                f"Value of cumulative associated output loss ({(cum_total or 0) * price:,.0f}) is below the change-out cost ({total_cost:,.0f})."
            )
        if samples_to_limit is not None and proj_idx is not None:
            reasons.append(f"Linear trend reaches {limit:g} mbar in ≈ {samples_to_limit:,.0f} hourly samples (sample #{proj_idx}).")
    if horizon_note:
        reasons.append(horizon_note)
    if rng and not (rng[0] <= limit <= rng[1]):
        reasons.append(
            f"Your limit {limit:g} mbar lies outside the training AFDP range {rng[0]:.2f}–{rng[1]:.2f} mbar; "
            "behaviour there was never observed in training."
        )

    series = []
    for p in downsample_positions(n):
        series.append(
            FilterSeriesPoint(
                row_index=int(rows[p]),
                afdp_rolling_mbar=_f(roll[p]),
                trend_mbar=_f(slope * p + intercept) if fit_lo <= p <= cur_pos else None,
                cumulative_loss_mwh=_f(cum[p]) if (penalty is not None and clean_pos <= p <= cur_pos) else None,
            )
        )

    coef_txt = f"{coef:.4f}" if coef is not None else "n/a"
    computation = (
        f"Trailing {w}-sample rolling median of AFDP for {n} hourly samples of {req.year}; current (sample #{int(rows[cur_pos])}) = {current:.3f} mbar. "
        f"Linear least-squares trend on the last {tw} samples: slope = {slope * 1000:.4f} mbar per 1000 samples, fitted value now = {fitted_now:.3f} mbar; "
        + (
            "limit already reached. "
            if limit_reached
            else (f"hours to {limit:g} mbar = ({limit:g} − {fitted_now:.3f}) / slope = {samples_to_limit:,.0f}. " if samples_to_limit is not None else "no crossing projected. ")
        )
        + f"Clean level = p{CLEAN_PERCENTILE:.0f} of the rolling AFDP = {clean:.3f} mbar (last at sample #{int(rows[clean_pos])}). "
        f"Output penalty = max(0, −OLS AFDP coefficient {coef_txt}) MWh per sample per mbar from training years {proxy.training_years} "
        f"({PROXY_STATEMENT.lower().rstrip('.')}). "
        + (
            f"Loss rate now = {penalty:.4f} × ({current:.3f} − {clean:.3f})⁺ = {rate_now:.4f} MWh/sample; cumulative since clean point = {cum_total:.2f} MWh. "
            if penalty is not None
            else ""
        )
        + f"Change-out cost = {req.filter_change_cost:,.0f} + {req.filter_outage_hours:g} h × median TEY {typical or 0:.2f} MWh × {price:g} = {total_cost:,.0f}. "
        + ("Break-even reached at sample #" + str(int(rows[be_pos])) + "." if break_even else "Break-even not reached in this year.")
        + (f" If the current rate persisted, payback ≈ {payback:,.0f} h." if payback is not None else "")
    )

    return FilterChangeoutResult(
        dataset_id=req.dataset_id,
        year=req.year,
        model_version=model_version,
        n_samples=n,
        rolling_window_samples=w,
        trend_window_samples=tw,
        current_index=int(rows[cur_pos]),
        status=status,
        status_reasons=reasons,
        afdp_limit_mbar=limit,
        current_afdp_rolling_mbar=_f(current),
        clean_afdp_mbar=_f(clean),
        clean_index=int(rows[clean_pos]),
        trend_slope_mbar_per_1000_samples=_f(slope * 1000.0),
        limit_reached=limit_reached,
        samples_to_limit=_f(samples_to_limit),
        projected_limit_index=proj_idx,
        afdp_training_range_mbar=rng,
        lost_output_rate_now_mwh_per_sample=_f(rate_now),
        cumulative_lost_output_mwh=_f(cum_total),
        typical_output_mwh_per_sample=_f(typical),
        economics={
            "energy_price_per_mwh": _f(price),
            "output_penalty_mwh_per_sample_per_mbar": _f(penalty),
            "loss_value_rate_now_per_hour": _f(rate_now * price) if rate_now is not None else None,
            "outage_lost_output_mwh": _f(outage_mwh),
            "outage_lost_output_value": _f(outage_mwh * price),
            "direct_cost": _f(req.filter_change_cost),
            "total_cost": _f(total_cost),
            "cumulative_loss_value": _f(cum_total * price) if cum_total is not None else None,
        },
        break_even_reached=break_even,
        break_even_index=int(rows[be_pos]) if be_pos is not None else None,
        payback_hours_if_rate_persists=_f(payback),
        proxy=proxy,
        series=series,
        projection=projection,
        computation=computation,
        assumptions=_assumptions(req, FILTER_SPEC),
        caveats=list(FILTER_CAVEATS),
    )


# ---------------------------------------------------------------------------
# Service wiring (repository + production baseline)
# ---------------------------------------------------------------------------

_proxy_lock = threading.Lock()
_proxy_cache: dict[tuple, AfdpProxy] = {}

MODEL_MISSING_MSG = "baseline model not trained yet (run `make train` or POST /api/models/train); the planner needs it"


def _require_model():
    from app import services

    model = services.get_model()
    if model is None:
        raise ModelMissingError(MODEL_MISSING_MSG)
    return model


def _year_frame(dataset_id: str, year: int):
    from app import services

    bundle = services.get_repo().get(dataset_id)  # KeyError -> 404
    years = bundle.years()
    if int(year) not in years:
        raise ValueError(f"year {year} not in dataset {dataset_id} (available: {', '.join(map(str, years)) or 'none'})")
    return bundle, bundle.year_frame(int(year))


def _training_range(model) -> Optional[list[float]]:
    try:
        r = model.evaluation.feature_ranges_train.get("AFDP")
        return [float(r[0]), float(r[1])] if r else None
    except Exception:  # noqa: BLE001
        return None


def run_compressor_wash(req: CompressorWashRequest) -> CompressorWashResult:
    model = _require_model()
    _, yf = _year_frame(req.dataset_id, req.year)
    residuals = model.residuals(yf) if len(yf) else np.array([], dtype=float)
    std = getattr(model.evaluation, "residual_std_validation", None)
    return compute_compressor_wash(yf, residuals, req, model_version=model.version, validation_residual_std=std)


def get_afdp_proxy(bundle, model) -> AfdpProxy:
    train_years = [int(y) for y in model.evaluation.split.train_years if int(y) in bundle.years()]
    key = (bundle.dataset_id, model.version, getattr(model.evaluation, "trained_at_utc", None), tuple(train_years), len(bundle.frame))
    with _proxy_lock:
        hit = _proxy_cache.get(key)
    if hit is not None:
        return hit
    tf = bundle.frame[bundle.frame["source_year"].isin(train_years)]
    proxy = estimate_afdp_proxy(tf, model, train_years)
    with _proxy_lock:
        _proxy_cache[key] = proxy
    return proxy


def run_filter_changeout(req: FilterChangeoutRequest) -> FilterChangeoutResult:
    model = _require_model()
    bundle, yf = _year_frame(req.dataset_id, req.year)
    proxy = get_afdp_proxy(bundle, model)
    return compute_filter_changeout(yf, req, proxy, model_version=model.version, afdp_training_range=_training_range(model))


def planner_options(dataset_id: str) -> PlannerOptions:
    from app import services

    wash_defaults = {k: CompressorWashRequest.model_fields[k].default for k, _, _ in WASH_SPEC if k not in ("dataset_id", "year")}
    filter_defaults = {k: FilterChangeoutRequest.model_fields[k].default for k, _, _ in FILTER_SPEC if k not in ("dataset_id", "year")}
    notes: list[str] = []
    years: list[int] = []
    try:
        years = services.get_repo().get(dataset_id).years()
    except KeyError:
        notes.append(f"dataset {dataset_id} not loaded (run `make data` or POST /api/datasets/seed-uci)")
    model = services.get_model()
    if model is None:
        notes.append("baseline model not trained yet (run `make train`); planner calculations need it")
    notes.append("All economic inputs are assumptions — edit them for your plant.")
    default_year = 2014 if 2014 in years else (years[-1] if years else None)
    return PlannerOptions(
        dataset_id=dataset_id,
        data_available=bool(years),
        years=years,
        default_year=default_year,
        model_available=model is not None,
        model_version=model.version if model is not None else None,
        afdp_training_range_mbar=_training_range(model) if model is not None else None,
        wash_defaults=wash_defaults,
        filter_defaults=filter_defaults,
        notes=notes,
    )
