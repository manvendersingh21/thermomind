"""Grid-support readiness indicators and contingency options (deterministic, advisory).

All MW-like numbers that come from the data are TEY values in MWh per ordered hourly sample (as published by
UCI; never converted). They are used as an *output proxy* only. Everything electrical (nameplate, inertia
constant H, power factor, network capacities) is a labelled ASSUMPTION supplied by the user with defaults.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.features.grid.schemas import (
    CardStatus,
    ContingencyAssumptions,
    ContingencyOption,
    ContingencyRequest,
    ContingencyResult,
    GridNumber,
    GridReadiness,
    ReadinessAssumptions,
    ReadinessCharts,
    ReadinessSummary,
    SeriesPt,
    StatusCard,
    TopologyNode,
)
from app.schemas import SampleRange

TRAIN_YEARS = (2011, 2012, 2013)
MIN_WINDOW_ROWS = 24
MAX_CHART_POINTS = 600

DEFAULT_NAMEPLATE_MW = 160.0
DEFAULT_H_S = 5.0
DEFAULT_PF = 0.85
H_TYPICAL_RANGE_S = [2.5, 6.0]
H_REFERENCE = (
    "Fernández-Guillamón et al. (2019), 'Power systems with high renewable energy sources: a review of inertia "
    "and frequency control strategies over time', Renewable and Sustainable Energy Reviews 115:109369, "
    "doi:10.1016/j.rser.2019.109369, Table 1: thermal (2-pole) 2.5-6 s citing Kundur et al. (1994); "
    "thermal (gas) 90-120 MW: 5 s; thermal (combined cycle) 115 MW: 4.3 s."
)
ASSUMPTION_LABEL = "ASSUMPTION (user input; not from the dataset)"



# ---------------------------------------------------------------------------
# Window + training statistics
# ---------------------------------------------------------------------------


def resolve_window(bundle, year: int, start: Optional[int], end: Optional[int],
                   min_rows: int = MIN_WINDOW_ROWS) -> tuple[pd.DataFrame, int, int]:
    """Return (window copy, start, end). ValueError -> 422; KeyError -> 404 (year absent)."""
    yf = bundle.year_frame(year)
    n = len(yf)
    if n == 0:
        raise KeyError(f"dataset '{bundle.dataset_id}' has no rows for year {year}")
    s = 0 if start is None else int(start)
    e = n if end is None else int(end)
    if s < 0 or e > n or e <= s:
        raise ValueError(f"window [{s}, {e}) is invalid for year {year} (need 0 <= start < end <= {n})")
    if e - s < min_rows:
        raise ValueError(f"window must contain at least {min_rows} rows (got {e - s})")
    return yf.iloc[s:e].reset_index(drop=True).copy(), s, e


@dataclass
class TrainStats:
    years: list[int]
    fallback: bool
    tit_p99: Optional[float]
    tit_max: Optional[float]
    tey_max: Optional[float]
    afdp_p50: Optional[float]
    afdp_p95: Optional[float]
    afdp_values: np.ndarray
    at_p50: Optional[float]
    tey_at_slope: Optional[float]
    tey_at_intercept: Optional[float]
    tey_at_r: Optional[float]
    rows: int


def _clean(series: pd.Series) -> np.ndarray:
    a = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return a[np.isfinite(a)]


def training_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[int], bool]:
    train = frame[frame["source_year"].isin(TRAIN_YEARS)]
    if len(train):
        return train, sorted(int(y) for y in train["source_year"].unique()), False
    return frame, sorted(int(y) for y in frame["source_year"].unique()), True


def linfit(x: np.ndarray, y: np.ndarray) -> tuple[Optional[float], Optional[float], Optional[float]]:
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 3 or float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return None, None, None
    slope, intercept = np.polyfit(x, y, 1)
    r = float(np.corrcoef(x, y)[0, 1])
    return float(slope), float(intercept), r


def training_stats(frame: pd.DataFrame) -> TrainStats:
    train, years, fallback = training_frame(frame)
    tit, tey, afdp, at = (_clean(train[c]) for c in ("TIT", "TEY", "AFDP", "AT"))
    slope, intercept, r = linfit(pd.to_numeric(train["AT"], errors="coerce").to_numpy(float),
                                 pd.to_numeric(train["TEY"], errors="coerce").to_numpy(float))
    q = lambda a, p: float(np.percentile(a, p)) if len(a) else None  # noqa: E731
    return TrainStats(
        years=years, fallback=fallback,
        tit_p99=q(tit, 99), tit_max=float(tit.max()) if len(tit) else None,
        tey_max=float(tey.max()) if len(tey) else None,
        afdp_p50=q(afdp, 50), afdp_p95=q(afdp, 95), afdp_values=np.sort(afdp),
        at_p50=q(at, 50), tey_at_slope=slope, tey_at_intercept=intercept, tey_at_r=r, rows=int(len(train)),
    )


def _r(v: Optional[float], d: int = 2) -> Optional[float]:
    return None if v is None or not math.isfinite(v) else round(float(v), d)


def _num(key, label, value, unit, provenance, computation, note=None, digits=2) -> GridNumber:
    return GridNumber(key=key, label=label, value=_r(value, digits), unit=unit, provenance=provenance,
                      computation=computation, note=note)


def _downsample(rows: np.ndarray, values: np.ndarray, start: int) -> tuple[list[SeriesPt], int]:
    n = len(values)
    step = max(1, math.ceil(n / MAX_CHART_POINTS))
    pts = [SeriesPt(row_index=int(start + i), value=_r(float(values[i]), 3) if np.isfinite(values[i]) else None)
           for i in range(0, n, step)]
    return pts, step


# ---------------------------------------------------------------------------
# Electrical assumptions (pure functions — unit-tested)
# ---------------------------------------------------------------------------


def apparent_power_mva(nameplate_mw: float, power_factor: float) -> float:
    return nameplate_mw / power_factor


def kinetic_energy_mws(h_s: float, s_mva: float) -> float:
    """E = H x S (MW·s = MJ)."""
    return h_s * s_mva


def reactive_at_rated_mvar(nameplate_mw: float, power_factor: float) -> float:
    return nameplate_mw * math.tan(math.acos(power_factor))


def reactive_circle_headroom_mvar(s_mva: float, p_now: float) -> float:
    """sqrt(S^2 - P^2): stator-current circle only (ignores field-heating / under-excitation limits)."""
    return math.sqrt(max(0.0, s_mva ** 2 - p_now ** 2))


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


_STATUS_ORDER = {"ok": 0, "info": 0, "watch": 1, "limited": 2}


def compute_readiness(bundle, year: int, start: Optional[int], end: Optional[int],
                      nameplate_mw: float = DEFAULT_NAMEPLATE_MW, h_constant_s: float = DEFAULT_H_S,
                      power_factor: float = DEFAULT_PF, computed_at_utc: str = "") -> GridReadiness:
    window, s, e = resolve_window(bundle, year, start, end)
    ts = training_stats(bundle.frame)
    yrs = f"{ts.years[0]}-{ts.years[-1]}" if ts.years else "n/a"
    tey = pd.to_numeric(window["TEY"], errors="coerce").to_numpy(float)
    tit = pd.to_numeric(window["TIT"], errors="coerce").to_numpy(float)
    afdp = pd.to_numeric(window["AFDP"], errors="coerce").to_numpy(float)
    at = pd.to_numeric(window["AT"], errors="coerce").to_numpy(float)
    n = len(window)
    rng_label = f"{year} samples #{s}-#{e - 1} (n={n})"

    tey_mean = float(np.nanmean(tey))
    tey_last = float(tey[np.isfinite(tey)][-1]) if np.isfinite(tey).any() else float("nan")
    tey_max = float(np.nanmax(tey))
    numbers: dict[str, GridNumber] = {}
    A = "assumption"

    # --- output proxy + headroom -------------------------------------------------------------------------
    numbers["output_proxy_mean"] = _num(
        "output_proxy_mean", "Output proxy (window mean TEY)", tey_mean, "MWh per hourly sample",
        "real_observation", f"mean(TEY) over {rng_label} = {tey_mean:.2f} MWh",
        "TEY is energy per ordered hourly sample (MWh, as published), used as an output proxy; not converted to MW.")
    numbers["output_proxy_last"] = _num(
        "output_proxy_last", "Last sample TEY", tey_last, "MWh per hourly sample", "real_observation",
        f"TEY at sample #{e - 1} = {tey_last:.2f} MWh")
    headroom = nameplate_mw - tey_mean
    exceed = int(np.sum(tey > nameplate_mw))
    numbers["headroom_to_nameplate"] = _num(
        "headroom_to_nameplate", "Headroom to nameplate (proxy)", headroom, "MWh/h (proxy)", A,
        f"nameplate {nameplate_mw:g} (ASSUMPTION) - mean TEY {tey_mean:.2f} = {headroom:.2f}",
        (f"{exceed} window samples exceed the nameplate assumption; the assumption may be low for this unit."
         if exceed else None))
    if ts.tey_max is not None:
        numbers["tey_max_train"] = _num(
            "tey_max_train", f"Historical max TEY ({yrs})", ts.tey_max, "MWh", "real_observation",
            f"max(TEY) over training years {yrs} (n={ts.rows}) = {ts.tey_max:.2f} MWh")

    # --- inertia -----------------------------------------------------------------------------------------
    s_mva = apparent_power_mva(nameplate_mw, power_factor)
    ke = kinetic_energy_mws(h_constant_s, s_mva)
    ke_lo, ke_hi = (kinetic_energy_mws(h, s_mva) for h in H_TYPICAL_RANGE_S)
    numbers["apparent_power_mva"] = _num(
        "apparent_power_mva", "Rated apparent power S", s_mva, "MVA", A,
        f"S = nameplate / pf = {nameplate_mw:g} / {power_factor:g} = {s_mva:.1f} MVA", digits=1)
    numbers["kinetic_energy_mws"] = _num(
        "kinetic_energy_mws", "Stored kinetic energy E = H x S", ke, "MW·s (MJ)", A,
        f"E = H x S = {h_constant_s:g} s x {s_mva:.1f} MVA = {ke:.0f} MW·s; typical-range H "
        f"{H_TYPICAL_RANGE_S[0]:g}-{H_TYPICAL_RANGE_S[1]:g} s gives {ke_lo:.0f}-{ke_hi:.0f} MW·s",
        "Synchronous inertia is inherent to a synchronised machine; it is a capability, not something this software acts on.",
        digits=0)

    # --- reactive ----------------------------------------------------------------------------------------
    q_rated = reactive_at_rated_mvar(nameplate_mw, power_factor)
    q_now = reactive_circle_headroom_mvar(s_mva, tey_mean)
    numbers["q_rated_mvar"] = _num(
        "q_rated_mvar", "Reactive capability at rated P (pf assumption)", q_rated, "Mvar", A,
        f"Q = P x tan(acos(pf)) = {nameplate_mw:g} x tan(acos({power_factor:g})) = {q_rated:.1f} Mvar", digits=1)
    numbers["q_headroom_proxy_mvar"] = _num(
        "q_headroom_proxy_mvar", "Reactive headroom proxy at window-mean output", q_now, "Mvar", A,
        f"sqrt(S^2 - P^2) = sqrt({s_mva:.1f}^2 - {tey_mean:.1f}^2) = {q_now:.1f} Mvar (P = mean TEY used as MW proxy)",
        "Stator-current circle only; real limits (field heating, under-excitation, voltage, OEM curve) are tighter.",
        digits=1)

    # --- thermal: TIT ------------------------------------------------------------------------------------
    tit_max_w = float(np.nanmax(tit))
    tit_mean_w = float(np.nanmean(tit))
    tit_margin = (ts.tit_p99 - tit_max_w) if ts.tit_p99 is not None else None
    numbers["tit_window_max"] = _num("tit_window_max", "TIT window max", tit_max_w, "°C", "real_observation",
                                     f"max(TIT) over {rng_label} = {tit_max_w:.1f} °C", digits=1)
    numbers["tit_p99_train"] = _num(
        "tit_p99_train", f"TIT historical p99 ({yrs})", ts.tit_p99, "°C", "derived_from_history",
        f"p99(TIT) over training years {yrs} (n={ts.rows}) = {ts.tit_p99:.1f} °C" if ts.tit_p99 is not None else "n/a",
        "Historical envelope, not an OEM limit.", digits=1)
    numbers["tit_margin_to_p99"] = _num(
        "tit_margin_to_p99", "TIT margin to historical p99", tit_margin, "°C", "derived_from_history",
        (f"p99 {ts.tit_p99:.1f} - window max {tit_max_w:.1f} = {tit_margin:.1f} °C" if tit_margin is not None else "n/a"),
        "How much hotter than this window the unit has historically run (p99). Historical envelope, not an OEM limit.",
        digits=1)
    if tit_margin is None:
        tit_status: CardStatus = "info"
    elif tit_margin < 2.0:
        # window max within 2 °C of the historical p99: TIT clusters at its ceiling at base load, which is normal
        # (temperature-controlled operation), so this is shown neutrally rather than as a limitation
        tit_status = "info"
    elif tit_margin < 10.0:
        tit_status = "watch"
    else:
        tit_status = "ok"

    # --- AFDP --------------------------------------------------------------------------------------------
    afdp_med = float(np.nanmedian(afdp))
    pct_rank = (float(np.searchsorted(ts.afdp_values, afdp_med, side="right")) / len(ts.afdp_values) * 100.0
                if len(ts.afdp_values) else None)
    numbers["afdp_window_median"] = _num("afdp_window_median", "AFDP window median", afdp_med, "mbar",
                                         "real_observation", f"median(AFDP) over {rng_label} = {afdp_med:.3f} mbar",
                                         digits=3)
    numbers["afdp_percentile_vs_train"] = _num(
        "afdp_percentile_vs_train", f"AFDP percentile vs {yrs}", pct_rank, "%", "derived_from_history",
        (f"share of training AFDP samples <= {afdp_med:.3f} mbar = {pct_rank:.1f}% (train p50 {ts.afdp_p50:.3f}, "
         f"p95 {ts.afdp_p95:.3f})" if pct_rank is not None else "n/a"),
        "Higher intake differential pressure (filter loading) generally reduces available output.", digits=1)
    if pct_rank is None:
        afdp_status: CardStatus = "info"
    elif pct_rank >= 95:
        afdp_status = "limited"
    elif pct_rank >= 80:
        afdp_status = "watch"
    else:
        afdp_status = "ok"

    # --- ambient AT --------------------------------------------------------------------------------------
    at_mean = float(np.nanmean(at))
    numbers["at_window_mean"] = _num("at_window_mean", "Ambient temperature (window mean)", at_mean, "°C",
                                     "real_observation", f"mean(AT) over {rng_label} = {at_mean:.2f} °C")
    implied = None
    if ts.tey_at_slope is not None:
        numbers["tey_at_slope"] = _num(
            "tey_at_slope", f"Slope TEY vs AT ({yrs})", ts.tey_at_slope, "MWh per °C", "model_derived",
            f"OLS fit TEY = {ts.tey_at_intercept:.2f} + ({ts.tey_at_slope:.3f}) x AT over {ts.rows} training samples, "
            f"r = {ts.tey_at_r:.3f}",
            "Correlational across all operating points (load dispatch confounds it); not an OEM ambient derate curve.",
            digits=3)
        implied = ts.tey_at_slope * (at_mean - (ts.at_p50 or 0.0))
        numbers["at_implied_effect"] = _num(
            "at_implied_effect", "Implied TEY effect vs training-median AT", implied, "MWh", "model_derived",
            f"{ts.tey_at_slope:.3f} x ({at_mean:.2f} - median AT {ts.at_p50:.2f}) = {implied:.2f} MWh")
    at_status: CardStatus = "info" if implied is None else ("watch" if implied < -3.0 else "ok")

    # --- cards -------------------------------------------------------------------------------------------
    hr_status: CardStatus = "limited" if headroom < 0.05 * nameplate_mw else ("watch" if headroom < 0.15 * nameplate_mw else "ok")
    cards = [
        StatusCard(
            key="output_headroom", title="Output headroom (proxy)", status=hr_status,
            headline=f"{headroom:.1f} MWh/h headroom to the {nameplate_mw:g} nameplate assumption at mean TEY {tey_mean:.1f}",
            numbers=[numbers["output_proxy_mean"], numbers["headroom_to_nameplate"]]
            + ([numbers["tey_max_train"]] if "tey_max_train" in numbers else []),
            computation=numbers["headroom_to_nameplate"].computation,
            note="TEY (MWh per hourly sample) is a proxy for average output; nameplate is an assumption."),
        StatusCard(
            key="inertia", title="Inertia contribution (assumption)", status="info",
            headline=f"~{ke:.0f} MW·s stored kinetic energy (H={h_constant_s:g} s, S={s_mva:.0f} MVA)",
            numbers=[numbers["apparent_power_mva"], numbers["kinetic_energy_mws"]],
            computation=numbers["kinetic_energy_mws"].computation,
            note=f"H typical range {H_TYPICAL_RANGE_S[0]:g}-{H_TYPICAL_RANGE_S[1]:g} s. Source: {H_REFERENCE}"),
        StatusCard(
            key="reactive", title="Reactive capability proxy (assumption)", status="info",
            headline=f"~{q_now:.0f} Mvar circle headroom at window-mean output; {q_rated:.0f} Mvar at rated P, pf {power_factor:g}",
            numbers=[numbers["q_rated_mvar"], numbers["q_headroom_proxy_mvar"]],
            computation=numbers["q_headroom_proxy_mvar"].computation,
            note="Voltage support capability must be confirmed against the OEM capability curve and grid-code requirements."),
        StatusCard(
            key="thermal_tit", title="Thermal margin: TIT vs historical envelope", status=tit_status,
            headline=((("At historical ceiling (normal for base load): " if tit_margin < 2.0 else "")
                       + f"{tit_margin:.1f} °C below the historical p99 ({ts.tit_p99:.1f} °C)") if tit_margin is not None
                      else "No training-year TIT available"),
            numbers=[numbers["tit_window_max"], numbers["tit_p99_train"], numbers["tit_margin_to_p99"]],
            computation=numbers["tit_margin_to_p99"].computation,
            note=(f"Historical envelope, not an OEM limit. Training-year TIT p99 {ts.tit_p99:.1f} °C vs max "
                  f"{ts.tit_max:.1f} °C: TIT clusters near its ceiling at high load, which may reflect a temperature-"
                  "controlled operating limit; a small margin means the window sits at the top of the historical "
                  "envelope, not that any limit was exceeded." if ts.tit_p99 is not None and ts.tit_max is not None
                  else "Historical envelope, not an OEM limit.")),
        StatusCard(
            key="intake_afdp", title="Intake restriction: AFDP", status=afdp_status,
            headline=(f"AFDP median {afdp_med:.2f} mbar; percentile rank {pct_rank:.0f}% within {yrs}" if pct_rank is not None
                      else f"AFDP median {afdp_med:.2f} mbar"),
            numbers=[numbers["afdp_window_median"], numbers["afdp_percentile_vs_train"]],
            computation=numbers["afdp_percentile_vs_train"].computation,
            note="Intake restriction reduces available output."),
        StatusCard(
            key="ambient_at", title="Ambient: AT effect on output", status=at_status,
            headline=(f"AT {at_mean:.1f} °C; training slope {ts.tey_at_slope:.2f} MWh/°C -> {implied:+.1f} MWh vs median AT"
                      if implied is not None else f"AT {at_mean:.1f} °C"),
            numbers=[numbers["at_window_mean"]] + [numbers[k] for k in ("tey_at_slope", "at_implied_effect") if k in numbers],
            computation=numbers.get("at_implied_effect", numbers["at_window_mean"]).computation,
            note="High AT reduces GT output (lower air density); the slope is statistical, not causal."),
    ]
    worst = max(cards, key=lambda c: _STATUS_ORDER[c.status])
    overall: CardStatus = worst.status if _STATUS_ORDER[worst.status] > 0 else "ok"
    bullets = [f"{c.title}: {c.headline}" for c in cards]
    headline = {
        "ok": "No thermal or intake indicator near its historical envelope in this window.",
        "watch": f"Watch: {', '.join(c.title for c in cards if c.status == 'watch')}.",
        "limited": f"Limited margin: {', '.join(c.title for c in cards if c.status == 'limited')}.",
    }[overall]

    tey_pts, step = _downsample(np.arange(n), tey, s)
    tit_pts, _ = _downsample(np.arange(n), tit, s)
    notes = [
        "TEY is published as MWh per ordered hourly sample; it is used as an output proxy and never converted to MW.",
        "No row-level timestamps exist; samples are referenced by source_year + row index.",
        f"Training-year statistics use {yrs} ({ts.rows} rows)"
        + (" — training years 2011-2013 not present, so ALL dataset rows were used." if ts.fallback else "."),
        "Nameplate, inertia constant H and power factor are user ASSUMPTIONS, not dataset values.",
        "TIT p99 is a historical envelope of this public dataset, not an OEM limit.",
        "This is read-only decision support: no setpoint or control action is produced.",
    ]
    return GridReadiness(
        dataset_id=bundle.dataset_id, year=year, window=SampleRange(source_year=year, start=s, end=e), rows=n,
        training_years=ts.years,
        assumptions=ReadinessAssumptions(
            nameplate_mw=nameplate_mw, h_constant_s=h_constant_s, power_factor=power_factor,
            h_typical_range_s=list(H_TYPICAL_RANGE_S), h_reference=H_REFERENCE,
            labels={"nameplate_mw": ASSUMPTION_LABEL, "h_constant_s": ASSUMPTION_LABEL,
                    "power_factor": ASSUMPTION_LABEL}),
        numbers=numbers, cards=cards,
        summary=ReadinessSummary(status=overall, headline=headline, bullets=bullets),
        charts=ReadinessCharts(tey=tey_pts, tit=tit_pts, nameplate_mw=nameplate_mw,
                               tit_p99_train=_r(ts.tit_p99, 2), downsample_factor=step),
        method_notes=notes, computed_at_utc=computed_at_utc,
    )


# ---------------------------------------------------------------------------
# Contingency options (SIMULATED topology)
# ---------------------------------------------------------------------------

_DEP_RANK = {"plant_internal": 0, "site": 1, "network_operator": 2, "tso_external": 3}
NOTIFY = ["dispatch/TSO", "shift_supervisor", "electrical_engineer"]
SHORTFALL_SEMANTICS = (
    "shortfall_mw = MW that must be relieved or replaced: for transformer_thermal / line_limit it is the flow above "
    "the reduced rating of the constrained element; for unit_derate it is the committed output this unit can no "
    "longer deliver. A user-supplied shortfall_mw is used as-is."
)


def _derive_shortfall(constraint: str, output: float, a: ContingencyAssumptions) -> tuple[float, str]:
    sev = a.severity_pct / 100.0
    if constraint == "transformer_thermal":
        limit = a.transformer_mva * a.power_factor * (1 - sev)
        sf = max(0.0, output - limit)
        return sf, (f"transformer limit = {a.transformer_mva:g} MVA x pf {a.power_factor:g} x (1 - {a.severity_pct:g}%) "
                    f"= {limit:.1f} MW; shortfall = max(0, output {output:.1f} - {limit:.1f}) = {sf:.1f} MW")
    if constraint == "line_limit":
        flow_a = output * a.share_to_a
        limit = a.line_a_rating_mw * (1 - sev)
        sf = max(0.0, flow_a - limit)
        return sf, (f"line A flow = output {output:.1f} x share {a.share_to_a:g} = {flow_a:.1f} MW; reduced rating = "
                    f"{a.line_a_rating_mw:g} x (1 - {a.severity_pct:g}%) = {limit:.1f} MW; shortfall = "
                    f"max(0, {flow_a:.1f} - {limit:.1f}) = {sf:.1f} MW")
    limit = a.nameplate_mw * (1 - sev)
    sf = max(0.0, output - limit)
    return sf, (f"derated capability = nameplate {a.nameplate_mw:g} x (1 - {a.severity_pct:g}%) = {limit:.1f} MW; "
                f"shortfall = max(0, output {output:.1f} - {limit:.1f}) = {sf:.1f} MW")


def enumerate_options(shortfall: float, output: float, constraint: Optional[str], a: ContingencyAssumptions,
                      tit_margin: Optional[float]) -> list[ContingencyOption]:
    """Pure function: ranked options for HUMAN evaluation. Never executes anything."""
    if shortfall <= 1e-9:
        return []
    sev = a.severity_pct / 100.0
    min_stable = a.min_stable_mw if a.min_stable_mw is not None else 0.5 * a.nameplate_mw
    flow_a = output * a.share_to_a
    flow_b = output * (1 - a.share_to_a)
    rating_a = a.line_a_rating_mw * (1 - sev) if constraint == "line_limit" else a.line_a_rating_mw
    tit_txt = (f"TIT margin to historical p99 = {tit_margin:.1f} °C (historical envelope, not an OEM limit)"
               if tit_margin is not None else "TIT margin unavailable")
    raw: list[dict] = []

    # (1) partial derate of this unit
    if constraint == "unit_derate":
        cov1, x = 0.0, output
        comp1 = ("not applicable: the unit itself is the derated element, so a further derate cannot replace "
                 "the lost output")
    else:
        cov1 = max(0.0, min(shortfall, output - min_stable))
        x = output - cov1
        comp1 = (f"covered = min(shortfall {shortfall:.1f}, output {output:.1f} - min stable {min_stable:.1f}) = "
                 f"{cov1:.1f} MW -> evaluate operating at X = {x:.1f} MW; {tit_txt}")
    raw.append(dict(
        option_id="unit_partial_derate", title="Evaluate a lower operating point for this unit (operator/dispatch decision)",
        description="Lower operating point for this unit to relieve the constrained element, if dispatch and the "
                    "grid code allow it.",
        covered=cov1, dep="plant_internal", computation=comp1,
        prerequisites=["dispatch/TSO agreement on the revised schedule per grid code",
                       "unit operating envelope confirmed by the shift supervisor (minimum stable load, emissions)",
                       f"thermal context checked: {tit_txt}"]))

    # (2) second unit
    cov2 = max(0.0, min(shortfall, a.second_unit_available_mw))
    raw.append(dict(
        option_id="second_unit_shift", title=f"Evaluate shifting ~{cov2:.0f} MW to the second unit",
        description="Share of the requirement carried by a second unit on site, if one is available.",
        covered=cov2, dep="site",
        computation=f"covered = min(shortfall {shortfall:.1f}, second-unit availability {a.second_unit_available_mw:.1f} "
                    f"(ASSUMPTION)) = {cov2:.1f} MW",
        prerequisites=["second unit availability confirmed by operations",
                       "dispatch/TSO approval of the revised unit schedules",
                       "evacuation path of the second unit checked for the same constraint"]))

    # (3) TSO re-dispatch
    tso_cap = shortfall if a.tso_redispatch_assumed_mw is None else a.tso_redispatch_assumed_mw
    cov3 = max(0.0, min(shortfall, tso_cap))
    raw.append(dict(
        option_id="tso_redispatch", title=f"Evaluate requesting TSO re-dispatch for ~{cov3:.0f} MW (TSO decision)",
        description="External: the TSO decides whether and how other resources cover the requirement.",
        covered=cov3, dep="tso_external",
        computation=(f"covered = min(shortfall {shortfall:.1f}, assumed TSO cover "
                     f"{'= full request' if a.tso_redispatch_assumed_mw is None else f'{tso_cap:.1f}'} (ASSUMPTION)) "
                     f"= {cov3:.1f} MW; actual amount is at the TSO's discretion"),
        prerequisites=["any request made through the agreed TSO communication channel by authorised staff",
                       "TSO acceptance; outcome is outside plant control",
                       "grid-code notification timelines observed"]))

    # (4) substation spare capacity bounded by line headroom
    head_a = max(0.0, rating_a - flow_a)
    head_b = max(0.0, a.line_b_rating_mw - flow_b)
    avail_a = min(a.ss_a_spare_mw, head_a)
    avail_b = min(a.ss_b_spare_mw, head_b)
    cov4 = max(0.0, min(shortfall, avail_a + avail_b))
    raw.append(dict(
        option_id="substation_spare", title=f"Evaluate using spare capacity at SS-A / SS-B (~{cov4:.0f} MW)",
        description="Spare capacity at nearby substations, bounded by their spare MW and the headroom on the "
                    "connecting lines (SIMULATED topology).",
        covered=cov4, dep="network_operator",
        computation=(f"SS-A: min(spare {a.ss_a_spare_mw:g}, line A headroom {rating_a:.1f} - {flow_a:.1f} = {head_a:.1f}) "
                     f"= {avail_a:.1f}; SS-B: min(spare {a.ss_b_spare_mw:g}, line B headroom {a.line_b_rating_mw:g} - "
                     f"{flow_b:.1f} = {head_b:.1f}) = {avail_b:.1f}; covered = min({shortfall:.1f}, "
                     f"{avail_a + avail_b:.1f}) = {cov4:.1f} MW"),
        prerequisites=["grid-code / TSO (or DSO) approval of any network reconfiguration",
                       "switching only by authorised personnel under a valid switching permit",
                       "protection settings checked for the alternative configuration by the electrical engineer"]))

    options: list[ContingencyOption] = []
    for r in raw:
        cov = round(r["covered"], 2)
        options.append(ContingencyOption(
            option_id=r["option_id"], rank=0, title=r["title"], description=r["description"],
            applicable=cov > 0, covered_mw=cov, residual_shortfall_mw=round(max(0.0, shortfall - cov), 2),
            external_dependency=r["dep"], prerequisites=r["prerequisites"], who_to_notify=list(NOTIFY),
            computation=r["computation"]))
    options.sort(key=lambda o: (o.residual_shortfall_mw, _DEP_RANK[o.external_dependency]))
    for i, o in enumerate(options, 1):
        o.rank = i
    return options


def build_topology(output: float, a: ContingencyAssumptions, constraint: Optional[str]) -> list[TopologyNode]:
    sev = a.severity_pct / 100.0
    t_rating = a.transformer_mva * (1 - sev) if constraint == "transformer_thermal" else a.transformer_mva
    la = a.line_a_rating_mw * (1 - sev) if constraint == "line_limit" else a.line_a_rating_mw
    unit_cap = a.nameplate_mw * (1 - sev) if constraint == "unit_derate" else a.nameplate_mw
    return [
        TopologyNode(node_id="gt", label="GT unit", kind="unit", capacity=round(unit_cap, 1), unit="MW",
                     flow_mw=round(output, 1), note="output = mean TEY proxy"),
        TopologyNode(node_id="gsu", label="Step-up transformer", kind="transformer", capacity=round(t_rating, 1), unit="MVA"),
        TopologyNode(node_id="line_a", label="Line A", kind="line", capacity=round(la, 1), unit="MW",
                     flow_mw=round(output * a.share_to_a, 1)),
        TopologyNode(node_id="line_b", label="Line B", kind="line", capacity=a.line_b_rating_mw, unit="MW",
                     flow_mw=round(output * (1 - a.share_to_a), 1)),
        TopologyNode(node_id="ss_a", label="SS-A", kind="substation", capacity=a.ss_a_spare_mw, unit="MW spare"),
        TopologyNode(node_id="ss_b", label="SS-B", kind="substation", capacity=a.ss_b_spare_mw, unit="MW spare"),
        TopologyNode(node_id="unit2", label="Second unit", kind="second_unit", capacity=a.second_unit_available_mw,
                     unit="MW available"),
    ]


def compute_contingency(bundle, req: ContingencyRequest, computed_at_utc: str = "") -> ContingencyResult:
    if req.shortfall_mw is None and req.constraint is None:
        raise ValueError("provide shortfall_mw or constraint (transformer_thermal | line_limit | unit_derate)")
    window, s, e = resolve_window(bundle, req.year, req.start, req.end)
    ts = training_stats(bundle.frame)
    tey = pd.to_numeric(window["TEY"], errors="coerce").to_numpy(float)
    tit = pd.to_numeric(window["TIT"], errors="coerce").to_numpy(float)
    output = float(np.nanmean(tey))
    tit_margin = (ts.tit_p99 - float(np.nanmax(tit))) if ts.tit_p99 is not None else None
    a = req.assumptions
    if req.shortfall_mw is not None:
        shortfall, src = float(req.shortfall_mw), "user_input"
        comp = f"shortfall = {shortfall:.1f} MW (user input)"
    else:
        shortfall, comp = _derive_shortfall(req.constraint, output, a)
        src = "derived_from_constraint"
    options = enumerate_options(shortfall, output, req.constraint, a, tit_margin)
    if not options:
        status, headline = "no_shortfall", "No shortfall under these assumptions: no contingency option is needed."
    else:
        best = options[0]
        if best.residual_shortfall_mw <= 1e-6:
            status, headline = "covered", f"{shortfall:.1f} MW: top-ranked option for evaluation is '{best.title}'."
        elif best.covered_mw > 0:
            status = "partially_covered"
            headline = (f"{shortfall:.1f} MW: no single option covers it; best leaves {best.residual_shortfall_mw:.1f} MW "
                        f"— consider escalating to dispatch/TSO (human decision).")
        else:
            status, headline = "not_covered", (f"{shortfall:.1f} MW: no option covers any of it under these "
                                               f"assumptions — consider escalating to dispatch/TSO (human decision).")
    labels = {k: ASSUMPTION_LABEL for k in ContingencyAssumptions.model_fields}
    return ContingencyResult(
        dataset_id=bundle.dataset_id, year=req.year, window=SampleRange(source_year=req.year, start=s, end=e),
        constraint=req.constraint, shortfall_mw=round(shortfall, 2), shortfall_source=src,
        shortfall_semantics=SHORTFALL_SEMANTICS, shortfall_computation=comp, output_proxy_mwh=round(output, 2),
        output_proxy_computation=f"mean(TEY) over {req.year} samples #{s}-#{e - 1} = {output:.2f} MWh per hourly sample (proxy)",
        tit_margin_c=_r(tit_margin, 1), assumptions=a, assumption_labels=labels,
        topology=build_topology(output, a, req.constraint), options=options, status=status, headline=headline,
        computed_at_utc=computed_at_utc,
    )
