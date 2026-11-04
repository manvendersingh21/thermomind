"""Thermal-monitoring engine: simulated thermal feed → status, screening flags, ageing, read-only advisories.

The feed is SIMULATED from the real UCI load proxy (TEY, MWh per hourly sample) and real ambient temperature
(AT, °C) using the planning models in ``model.py``. Nothing here reads a thermal sensor and nothing here writes
to any plant system. Advisories list options for people to EVALUATE; the software takes no action.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.analytics.anomaly import trend_slope
from app.features.thermal import model
from app.features.thermal.schemas import (
    PROVENANCE,
    READ_ONLY_SUFFIX,
    Advisory,
    Ageing,
    AssetInfo,
    AssetStatus,
    DemandImpactRow,
    DemandProfileInfo,
    DemandScenario,
    LimitLine,
    SeriesPoint,
    SyntheticDefect,
    ThermalAssumptions,
    ThermalEvaluateResponse,
    ThermalFlag,
    WindowInfo,
)

MIN_WINDOW = 24
MAX_WINDOW = 9000
MAX_POINTS = 1000
TREND_SAMPLES = 24
PEER_SLOPE_MARGIN = 0.002  # rise-index units per sample above the peer median (~ +5 % per 24 samples)
HOT_CONNECTION_DRIFT = 0.15  # this asset's load-corrected rise grew ≥ 15 % first-24 → last-24 samples
PEER_DRIFT_MAX = 0.05  # ... while every sibling stayed within ±5 %
DEFECT_ASSET = "HVSG"
CONNECTION_GROUP = ("GCB", "HVSG", "BUS")

ASSETS: list[AssetInfo] = [
    AssetInfo(asset_id="GEN", name="Generator", kind="generator stator winding", order=1, group="rotating",
              temperature_label="stator temperature (proxy)",
              model="θ = (AT + indoor offset) + Δθ_rated·K², K = TEY / generator_rated_mwh",
              standard_ref="I²R proxy; rated rise per IEC 60034-1 class B rise (80 K) used on class F (155 °C) insulation — confirm with OEM data",
              rating_param="generator_rated_mwh", rise_param="generator_rated_rise_k",
              alarm_param="generator_alarm_c", limit_param="generator_limit_c"),
    AssetInfo(asset_id="GCB", name="Generator breaker", kind="generator circuit-breaker main contacts", order=2,
              group="connection", temperature_label="contact temperature",
              model="θ = (AT + indoor offset) + Δθ_rated·K², K = TEY / generator_rated_mwh",
              standard_ref=("generator circuit-breaker standard IEEE C37.013 / IEC/IEEE 62271-37-013; typical type-test "
                            "temperature-rise limits (silver-plated contacts 65 K rise, 105 °C, per IEC 62271-1) — "
                            "confirm with equipment data"),
              rating_param="generator_rated_mwh", rise_param="contact_rated_rise_k",
              alarm_param="contact_alarm_c", limit_param="contact_limit_c"),
    AssetInfo(asset_id="GSU", name="Step-up transformer", kind="oil-immersed generator step-up transformer", order=3,
              group="transformer", temperature_label="hot-spot",
              model="IEEE C57.91 Clause 7 exponential top-oil + hot-spot model on hourly steps, ambient = AT",
              standard_ref="modelled after IEEE Std C57.91 (Clause 7 temperatures, Clause 5 ageing)",
              rating_param="transformer_rated_mwh", rise_param="top_oil_rise_rated_k",
              alarm_param="transformer_hot_spot_alarm_c", limit_param="transformer_hot_spot_limit_c"),
    AssetInfo(asset_id="HVSG", name="HV switchgear", kind="HV switchgear bay (breaker contacts, cable termination)", order=4,
              group="connection", temperature_label="contact temperature",
              model="θ = (AT + indoor offset) + Δθ_rated·K², K = TEY / hv_rated_mwh",
              standard_ref="typical type-test limits (IEC 62271-1 / IEEE C37.20.2: silver-plated contacts 65 K rise, 105 °C) — confirm with equipment data",
              rating_param="hv_rated_mwh", rise_param="contact_rated_rise_k",
              alarm_param="contact_alarm_c", limit_param="contact_limit_c"),
    AssetInfo(asset_id="BUS", name="HV busbar", kind="HV busbar and bolted joints", order=5, group="connection",
              temperature_label="busbar temperature",
              model="θ = (AT + indoor offset) + Δθ_rated·K², K = TEY / hv_rated_mwh",
              standard_ref="typical type-test limits (IEC 62271-1 bare-copper bolted joints 50 K rise, 90 °C) — confirm with equipment data",
              rating_param="hv_rated_mwh", rise_param="busbar_rated_rise_k",
              alarm_param="busbar_alarm_c", limit_param="busbar_limit_c"),
]
ASSET_BY_ID = {a.asset_id: a for a in ASSETS}

DEMAND_PROFILES = [
    DemandProfileInfo(profile="flat", description="constant multiplier on every sample (e.g. 1.15 = +15 % dispatch)"),
    DemandProfileInfo(
        profile="diurnal_datacenter",
        description="data-center demand growth: added demand with a ±25 % cooling-driven swing peaking at notional hour 15 "
        "(notional hour = row_index mod 24, not a clock time — UCI rows have no timestamps)",
    ),
]


@dataclass
class Feed:
    row_index: np.ndarray
    load: np.ndarray
    ambient: np.ndarray
    ambient_in: np.ndarray
    k_gen: np.ndarray
    k_tr: np.ndarray
    k_hv: np.ndarray
    temps: dict[str, np.ndarray]
    top_oil: np.ndarray
    lol_h: np.ndarray


def _alarm_limit(a: ThermalAssumptions, asset_id: str) -> tuple[float, float]:
    info = ASSET_BY_ID[asset_id]
    return float(getattr(a, info.alarm_param)), float(getattr(a, info.limit_param))


def _rated_rise(a: ThermalAssumptions, asset_id: str) -> float:
    return float(getattr(a, ASSET_BY_ID[asset_id].rise_param))


def _k_for(feed: Feed, asset_id: str) -> np.ndarray:
    return {"GEN": feed.k_gen, "GCB": feed.k_gen, "GSU": feed.k_tr, "HVSG": feed.k_hv, "BUS": feed.k_hv}[asset_id]


def simulate(row_index: np.ndarray, load: np.ndarray, ambient: np.ndarray, a: ThermalAssumptions,
             defect: Optional[tuple[str, float, int]] = None) -> Feed:
    """Simulated thermal feed for every asset. ``defect`` = (asset_id, growth, seed) injects the SYNTHETIC
    hot connection on a copy; inputs are never mutated."""
    load = np.asarray(load, dtype=float)
    amb = np.asarray(ambient, dtype=float)
    amb_in = amb + a.indoor_ambient_offset_k
    k_gen = model.load_ratio(load, a.generator_rated_mwh)
    k_tr = model.load_ratio(load, a.transformer_rated_mwh)
    k_hv = model.load_ratio(load, a.hv_rated_mwh)
    top_oil, hot_spot = model.transformer_transient(
        k_tr, amb, top_oil_rise_rated=a.top_oil_rise_rated_k, hot_spot_gradient_rated=a.hot_spot_gradient_rated_k,
        r=a.loss_ratio_r, n=a.exponent_n, m=a.exponent_m, tau_top_oil_h=a.tau_top_oil_h,
        tau_hot_spot_h=a.tau_hot_spot_h, dt_h=1.0,
    )
    temps = {
        "GEN": model.quadratic_rise_temperature(k_gen, amb_in, a.generator_rated_rise_k),
        "GCB": model.quadratic_rise_temperature(k_gen, amb_in, a.contact_rated_rise_k),
        "GSU": hot_spot,
        "HVSG": model.quadratic_rise_temperature(k_hv, amb_in, a.contact_rated_rise_k),
        "BUS": model.quadratic_rise_temperature(k_hv, amb_in, a.busbar_rated_rise_k),
    }
    feed = Feed(row_index=np.asarray(row_index), load=load, ambient=amb, ambient_in=amb_in, k_gen=k_gen, k_tr=k_tr,
                k_hv=k_hv, temps=temps, top_oil=top_oil, lol_h=model.cumulative_loss_of_life_h(hot_spot, 1.0))
    if defect is not None:
        asset_id, growth, seed = defect
        temps[asset_id] = model.inject_hot_connection(_k_for(feed, asset_id), amb_in, _rated_rise(a, asset_id), growth, seed)
    return feed


def _state(temp: float, alarm: float, limit: float, approach: float) -> str:
    if temp >= limit:
        return "limit"
    if temp >= alarm:
        return "alarm"
    if temp >= alarm - approach:
        return "approaching"
    return "normal"


def _nanmean(x: np.ndarray) -> Optional[float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(x.mean()) if x.size else None


def _f(x: Optional[float], nd: int = 3) -> Optional[float]:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), nd)


def _status(feed: Feed, a: ThermalAssumptions, defect_asset: Optional[str]) -> list[AssetStatus]:
    out = []
    for info in ASSETS:
        aid = info.asset_id
        t = feed.temps[aid]
        alarm, limit = _alarm_limit(a, aid)
        k = _k_for(feed, aid)
        amb = feed.ambient if aid == "GSU" else feed.ambient_in
        peak_i = int(np.nanargmax(t))
        ri_now = ri_drift = None
        if info.group == "connection":
            ri = model.load_corrected_rise_index(t, amb, k, _rated_rise(a, aid))
            ri_now = _nanmean(ri[-TREND_SAMPLES:])
            first = _nanmean(ri[:TREND_SAMPLES])
            ri_drift = (ri_now - first) if (ri_now is not None and first is not None) else None
        cur = float(t[-1])
        out.append(AssetStatus(
            asset_id=aid, name=info.name, state=_state(cur, alarm, limit, a.approach_margin_k),
            current_c=round(cur, 2), load_ratio_k=round(float(k[-1]), 4), ambient_c=round(float(amb[-1]), 2),
            alarm_c=alarm, limit_c=limit, margin_to_alarm_k=round(alarm - cur, 2), margin_to_limit_k=round(limit - cur, 2),
            peak_c=round(float(t[peak_i]), 2), peak_row_index=int(feed.row_index[peak_i]),
            trend_k_per_sample=_f(trend_slope(t[-TREND_SAMPLES:]), 4), trend_window_samples=min(TREND_SAMPLES, t.size),
            samples_above_alarm=int(np.sum(t >= alarm)), samples_above_limit=int(np.sum(t >= limit)),
            rise_index=_f(ri_now, 4), rise_index_drift=_f(ri_drift, 4),
            top_oil_c=round(float(feed.top_oil[-1]), 2) if aid == "GSU" else None,
            top_oil_limit_c=a.transformer_top_oil_limit_c if aid == "GSU" else None,
            synthetic=(aid == defect_asset),
        ))
    return out


def _peer_slopes(feed: Feed, a: ThermalAssumptions) -> dict[str, Optional[float]]:
    slopes: dict[str, Optional[float]] = {}
    for aid in CONNECTION_GROUP:
        ri = model.load_corrected_rise_index(feed.temps[aid], feed.ambient_in, _k_for(feed, aid), _rated_rise(a, aid))
        slopes[aid] = _f(trend_slope(ri[-TREND_SAMPLES:]), 6)
    return slopes


def _flags(status: list[AssetStatus], feed: Feed, a: ThermalAssumptions, defect_asset: Optional[str]) -> list[ThermalFlag]:
    flags: list[ThermalFlag] = []
    n = feed.load.size
    for s in status:
        syn = s.asset_id == defect_asset
        label = ASSET_BY_ID[s.asset_id].temperature_label
        if s.state == "limit":
            flags.append(ThermalFlag(asset_id=s.asset_id, flag="above_limit", severity="high", synthetic=syn,
                                     message=f"{s.name} {label} {s.current_c:.1f} °C is at/above the {s.limit_c:.0f} °C limit assumption"))
        elif s.state == "alarm":
            flags.append(ThermalFlag(asset_id=s.asset_id, flag="above_alarm", severity="warning", synthetic=syn,
                                     message=f"{s.name} {label} {s.current_c:.1f} °C is at/above the {s.alarm_c:.0f} °C alarm assumption"))
        elif s.state == "approaching":
            flags.append(ThermalFlag(asset_id=s.asset_id, flag="approaching_alarm", severity="watch", synthetic=syn,
                                     message=f"{s.name} {label} margin to alarm {s.margin_to_alarm_k:.1f} K (< {a.approach_margin_k:g} K)"))
        if s.state in ("normal", "approaching") and s.samples_above_alarm > 0:
            flags.append(ThermalFlag(asset_id=s.asset_id, flag="exceeded_alarm_in_window", severity="watch", synthetic=syn,
                                     message=f"{s.name} {label} was at/above alarm in {s.samples_above_alarm} of {n} samples "
                                             f"(peak {s.peak_c:.1f} °C at sample #{s.peak_row_index})"))
    slopes = _peer_slopes(feed, a)
    by_id = {s.asset_id: s for s in status}
    for aid in CONNECTION_GROUP:
        peers = [p for p in CONNECTION_GROUP if p != aid]
        syn = aid == defect_asset
        own = slopes[aid]
        peer_vals = [slopes[p] for p in peers if slopes[p] is not None]
        if own is not None and peer_vals and own - float(np.median(peer_vals)) > PEER_SLOPE_MARGIN:
            flags.append(ThermalFlag(asset_id=aid, flag="rising_faster_than_peers", severity="watch", synthetic=syn,
                                     message=f"{by_id[aid].name} load-corrected rise trending {own:+.4f}/sample over the last "
                                             f"{TREND_SAMPLES} samples vs peer median {float(np.median(peer_vals)):+.4f}/sample"))
        drift = by_id[aid].rise_index_drift
        peer_drifts = [by_id[p].rise_index_drift for p in peers]
        if (drift is not None and drift >= HOT_CONNECTION_DRIFT
                and all(d is not None and abs(d) < PEER_DRIFT_MAX for d in peer_drifts)):
            flags.append(ThermalFlag(asset_id=aid, flag="hot_connection_pattern", severity="warning", synthetic=syn,
                                     message=f"{by_id[aid].name} load-corrected rise grew {drift * 100:+.0f} % over the window "
                                             f"while siblings ({', '.join(peers)}) stayed within ±{PEER_DRIFT_MAX * 100:.0f} %"))
    return flags


def _ro(text: str) -> str:
    return f"{text} — {READ_ONLY_SUFFIX}"


def _advisories(status: list[AssetStatus], flags: list[ThermalFlag], a: ThermalAssumptions, n: int) -> list[Advisory]:
    out: list[Advisory] = []
    by_asset: dict[str, set[str]] = {}
    for f in flags:
        by_asset.setdefault(f.asset_id, set()).add(f.flag)
    sev_rank = {"info": 0, "watch": 1, "warning": 2, "high": 3}
    for s in status:
        kinds = by_asset.get(s.asset_id, set())
        if not kinds:
            continue
        label = ASSET_BY_ID[s.asset_id].temperature_label
        sev = max((f.severity for f in flags if f.asset_id == s.asset_id), key=lambda v: sev_rank[v])
        if kinds & {"above_limit", "above_alarm", "approaching_alarm"}:
            if s.margin_to_alarm_k >= 0:
                head = f"{label} margin < {a.approach_margin_k:g} K ({s.margin_to_alarm_k:.1f} K to the {s.alarm_c:.0f} °C alarm)"
            else:
                head = f"{label} is {-s.margin_to_alarm_k:.1f} K above the {s.alarm_c:.0f} °C alarm assumption"
            out.append(Advisory(asset_id=s.asset_id, kind="margin", severity=sev, synthetic=s.synthetic, text=_ro(
                f"Advisory: {s.name} {head} at the last-sample-of-window load ratio K = {s.load_ratio_k:.2f}; options for the operator/dispatch "
                f"to EVALUATE per site procedure: schedule inspection (IR survey) of {s.name}, review load allocation, "
                f"consider derate planning")))
        elif "exceeded_alarm_in_window" in kinds:
            out.append(Advisory(asset_id=s.asset_id, kind="margin", severity=sev, synthetic=s.synthetic, text=_ro(
                f"Advisory: {s.name} {label} was at/above the {s.alarm_c:.0f} °C alarm assumption in {s.samples_above_alarm} "
                f"of {n} samples (peak {s.peak_c:.1f} °C at sample #{s.peak_row_index}); options for the operator/dispatch to "
                f"EVALUATE per site procedure: schedule inspection (IR survey) of {s.name}, review load allocation for "
                f"similar conditions, consider derate planning")))
        if "hot_connection_pattern" in kinds:
            tag = " [SYNTHETIC scenario T01_HOT_CONNECTION]" if s.synthetic else ""
            out.append(Advisory(asset_id=s.asset_id, kind="hot_connection", severity=sev, synthetic=s.synthetic, text=_ro(
                f"Advisory: {s.name} shows a hot-connection pattern{tag} — load-corrected rise grew "
                f"{(s.rise_index_drift or 0) * 100:.0f} % over the window while sibling connections stayed flat; options "
                f"for maintenance/operations to EVALUATE per site procedure: schedule an IR survey of the {s.name} "
                f"terminations and bolted joints, plan a contact-resistance and torque check at the next planned outage, "
                f"review load allocation in the meantime")))
        elif "rising_faster_than_peers" in kinds:
            out.append(Advisory(asset_id=s.asset_id, kind="trend", severity=sev, synthetic=s.synthetic, text=_ro(
                f"Advisory: {s.name} load-corrected rise is trending up faster than its peers over the last "
                f"{TREND_SAMPLES} samples; options for maintenance to EVALUATE per site procedure: schedule an IR survey "
                f"of {s.name} and compare with the previous survey")))
    return out


def _ageing(feed: Feed, a: ThermalAssumptions) -> Ageing:
    hs = feed.temps["GSU"]
    faa = model.ageing_acceleration_factor(hs)
    lol_h = float(feed.lol_h[-1])
    feqa = float(np.mean(faa))
    return Ageing(
        current_faa=round(float(faa[-1]), 6), equivalent_faa=round(feqa, 6), loss_of_life_h=round(lol_h, 4),
        loss_of_life_pct=round(100.0 * lol_h / a.normal_insulation_life_h, 6), window_hours=int(hs.size),
        normal_insulation_life_h=a.normal_insulation_life_h,
        extrapolated_loss_of_life_pct_per_year=round(100.0 * feqa * model.HOURS_PER_YEAR / a.normal_insulation_life_h, 4),
    )


def _downsample(feed: Feed, a: ThermalAssumptions, whatif: Optional[Feed]) -> tuple[list[SeriesPoint], int]:
    n = feed.load.size
    step = max(1, math.ceil(n / MAX_POINTS))
    lol_pct = 100.0 * feed.lol_h / a.normal_insulation_life_h
    lol_pct_w = 100.0 * whatif.lol_h / a.normal_insulation_life_h if whatif is not None else None
    pts = []
    for s in range(0, n, step):
        e = min(n, s + step)
        sl = slice(s, e)
        pts.append(SeriesPoint(
            row_index=int(feed.row_index[s]), ambient_c=round(float(np.mean(feed.ambient[sl])), 2),
            load_mwh=round(float(np.mean(feed.load[sl])), 3), load_ratio_k=round(float(np.mean(feed.k_gen[sl])), 4),
            GEN=round(float(np.max(feed.temps["GEN"][sl])), 2), GCB=round(float(np.max(feed.temps["GCB"][sl])), 2),
            GSU=round(float(np.max(feed.temps["GSU"][sl])), 2), GSU_TOP_OIL=round(float(np.max(feed.top_oil[sl])), 2),
            HVSG=round(float(np.max(feed.temps["HVSG"][sl])), 2), BUS=round(float(np.max(feed.temps["BUS"][sl])), 2),
            lol_cum_pct=round(float(lol_pct[e - 1]), 6),
            GSU_whatif=round(float(np.max(whatif.temps["GSU"][sl])), 2) if whatif is not None else None,
            lol_cum_pct_whatif=round(float(lol_pct_w[e - 1]), 6) if lol_pct_w is not None else None,
        ))
    return pts, step


def _demand(base: Feed, a: ThermalAssumptions, multiplier: Optional[float], profile: str,
            defect: Optional[tuple[str, float, int]]) -> tuple[DemandScenario, Optional[Feed], list[Advisory]]:
    applied = multiplier is not None and abs(multiplier - 1.0) > 1e-9
    mult = float(multiplier) if multiplier is not None else 1.0
    desc = next(p.description for p in DEMAND_PROFILES if p.profile == profile)
    hour_note = ("notional hour = row_index mod 24; UCI rows have no timestamps, so this is NOT a clock time"
                 if profile == "diurnal_datacenter" else None)
    above_np_base = int(np.sum(base.k_gen > 1.0))
    if not applied:
        return DemandScenario(applied=False, multiplier=mult, profile=profile, description=desc, notional_hour_note=hour_note,
                              samples_above_nameplate_baseline=above_np_base, samples_above_nameplate_scenario=above_np_base), None, []
    m = model.demand_multiplier_profile(base.row_index, mult, profile)
    feed = simulate(base.row_index, base.load * m, base.ambient, a, defect)
    defect_asset = defect[0] if defect else None
    scen_status = _status(feed, a, defect_asset)
    base_status = {s.asset_id: s for s in _status(base, a, defect_asset)}
    rows, advs = [], []
    n = base.load.size
    for s in scen_status:
        b = base_status[s.asset_id]
        rows.append(DemandImpactRow(
            asset_id=s.asset_id, baseline_peak_c=b.peak_c, scenario_peak_c=s.peak_c, delta_peak_k=round(s.peak_c - b.peak_c, 2),
            baseline_samples_above_alarm=b.samples_above_alarm, scenario_samples_above_alarm=s.samples_above_alarm,
            baseline_samples_above_limit=b.samples_above_limit, scenario_samples_above_limit=s.samples_above_limit,
        ))
        if s.samples_above_alarm > b.samples_above_alarm or s.peak_c >= s.alarm_c - a.approach_margin_k > b.peak_c:
            label = ASSET_BY_ID[s.asset_id].temperature_label
            sev = "high" if s.samples_above_limit > 0 else ("warning" if s.samples_above_alarm > 0 else "watch")
            advs.append(Advisory(asset_id=s.asset_id, kind="demand_scenario", severity=sev, what_if=True, synthetic=s.synthetic, text=_ro(
                f"Advisory (what-if, demand x{mult:.2f} {profile}): {s.name} {label} would be at/above the {s.alarm_c:.0f} °C "
                f"alarm in {s.samples_above_alarm} of {n} samples (baseline {b.samples_above_alarm}) and above the "
                f"{s.limit_c:.0f} °C limit in {s.samples_above_limit}; peak {s.peak_c:.1f} °C vs {b.peak_c:.1f} °C baseline. "
                f"Options for planners/dispatch to EVALUATE before committing to the additional demand: review load "
                f"allocation, consider derate planning or a rating review of the {s.name}")))
    lol_b = round(100.0 * float(base.lol_h[-1]) / a.normal_insulation_life_h, 6)
    lol_s = round(100.0 * float(feed.lol_h[-1]) / a.normal_insulation_life_h, 6)
    return DemandScenario(
        applied=True, multiplier=mult, profile=profile, description=desc, notional_hour_note=hour_note,
        samples_above_nameplate_baseline=above_np_base, samples_above_nameplate_scenario=int(np.sum(feed.k_gen > 1.0)),
        impact=rows, scenario_status=scen_status, baseline_loss_of_life_pct=lol_b, scenario_loss_of_life_pct=lol_s,
    ), feed, advs


def _clean_inputs(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    for col in ("TEY", "AT", "row_index"):
        if col not in frame.columns:
            raise ValueError(f"window is missing required column {col}")
    tey = pd.to_numeric(frame["TEY"], errors="coerce")
    at = pd.to_numeric(frame["AT"], errors="coerce")
    if tey.notna().sum() == 0 or at.notna().sum() == 0:
        raise ValueError("window has no usable TEY/AT values")
    tey = tey.ffill().bfill()
    at = at.ffill().bfill()
    return frame["row_index"].to_numpy(dtype=int), tey.to_numpy(dtype=float), at.to_numpy(dtype=float)


def evaluate(frame: pd.DataFrame, *, dataset_id: str, year: int, start: int, end: int,
             assumptions: Optional[ThermalAssumptions] = None, scenario: str = "none", scenario_seed: int = 42,
             demand_multiplier: Optional[float] = None, demand_profile: str = "flat") -> ThermalEvaluateResponse:
    """``frame`` is the real [start, end) window (columns row_index, TEY, AT). Never mutated."""
    a = assumptions or ThermalAssumptions()
    if scenario not in ("none", "T01_HOT_CONNECTION"):
        raise ValueError(f"unknown scenario '{scenario}' (expected none or T01_HOT_CONNECTION)")
    if demand_profile not in ("flat", "diurnal_datacenter"):
        raise ValueError(f"unknown demand_profile '{demand_profile}'")
    n = len(frame)
    if n < MIN_WINDOW:
        raise ValueError(f"window must contain at least {MIN_WINDOW} samples (got {n})")
    if n > MAX_WINDOW:
        raise ValueError(f"window must contain at most {MAX_WINDOW} samples (got {n})")
    ri, tey, at = _clean_inputs(frame)
    defect = (DEFECT_ASSET, a.hot_connection_growth, int(scenario_seed)) if scenario == "T01_HOT_CONNECTION" else None
    defect_asset = defect[0] if defect else None

    base = simulate(ri, tey, at, a, defect)
    status = _status(base, a, defect_asset)
    flags = _flags(status, base, a, defect_asset)
    advisories = _advisories(status, flags, a, n)
    demand, whatif, demand_adv = _demand(base, a, demand_multiplier, demand_profile, defect)
    advisories.extend(demand_adv)
    series, step = _downsample(base, a, whatif)
    synthetic_defect = None
    if defect is not None:
        synthetic_defect = SyntheticDefect(
            scenario="T01_HOT_CONNECTION", asset_id=DEFECT_ASSET, growth=a.hot_connection_growth, seed=int(scenario_seed),
            description=(f"SYNTHETIC degrading connection at the {ASSET_BY_ID[DEFECT_ASSET].name} (cable termination / bolted "
                         f"joint): rise coefficient grows linearly from 1.0x to {1 + a.hot_connection_growth:.2f}x over the "
                         f"window plus seeded jitter (sigma 0.3 K). Real rows are not modified."),
        )
    return ThermalEvaluateResponse(
        dataset_id=dataset_id, window=WindowInfo(source_year=year, start=start, end=end, n_samples=n),
        provenance=PROVENANCE, synthetic=defect is not None, scenario=scenario, synthetic_defect=synthetic_defect,
        demand=demand, status=status, flags=flags, advisories=advisories, ageing=_ageing(base, a),
        limits=[LimitLine(asset_id=s.asset_id, alarm_c=s.alarm_c, limit_c=s.limit_c) for s in status],
        series=series, downsample_factor=step, assumptions=a,
    )
