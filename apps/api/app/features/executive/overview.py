"""Aggregate what ThermoMind already measures into a CEO-level overview.

Every KPI carries {value, unit, provenance, source_endpoint, caveat}. Nothing here invents a number: each value is
computed by an existing engine (baseline residuals, planner, instrument scorecard, emissions screening, thermal
model, grid readiness, ops metrics) or counted from an existing table. Sibling workstreams that may be absent
(collab, deliberation, watchdog) are read through guarded imports / guarded SQL and reported as unavailable.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from app import config
from app.features.executive.schemas import AttentionItem, ExecutiveOverview, Kpi, OpenCase

log = logging.getLogger("thermomind.executive.overview")

DEFAULT_DATASET_ID = "ds_uci_551"
NOTABLE_Z = 2.0             # same rule as the evidence engine (app.analytics.evidence.NOTABLE_Z)
ROLL_WINDOW = 24            # rolling case window: 24 hourly samples
ROLL_REFERENCE = 168        # reference: the 168 samples preceding each window (evidence-engine style)
THERMAL_WINDOW = 120        # "latest window" for the thermal model: last 120 samples of the year
THERMAL_MARGIN_RULE_K = 10.0  # attention rule; equals the thermal engine's default 'approaching' band
REVIEWED = ("accepted", "rejected", "more_data_requested")

PERSONA_NAMES = {
    "plant_manager": "Plant manager",
    "shift_supervisor": "Shift supervisor",
    "performance_engineer": "Performance engineer",
    "reliability_engineer": "Reliability engineer",
    "ic_engineer": "I&C engineer",
    "electrical_engineer": "Electrical engineer",
    "environmental_engineer": "Environmental / compliance engineer",
    "hse_officer": "HSE officer",
}


def _r(x: Any, nd: int = 2) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


# ----------------------------------------------------------------------------- sources (patchable)
def _db_path() -> Path:
    return Path(config.DB_PATH)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def count_table(name: str) -> Optional[int]:
    """Row count of a table, or None when the DB/table does not exist (read-only; never creates it)."""
    path = _db_path()
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
            if not _table_exists(conn, name):
                return None
            return int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])  # name is a constant
    except sqlite3.Error:
        return None


def _default_bundle(dataset_id: str):
    from app import services

    return services.get_repo().get(dataset_id)


def _default_model():
    from app import services

    return services.get_model()


def _default_investigations() -> list[Any]:
    from app import services

    return services.get_store().list()


def _default_work_requests() -> Optional[list[Any]]:
    try:
        from app.plant import store as plant_store  # guarded: plant-ops workstream

        return plant_store.list_work_requests()
    except Exception as exc:  # noqa: BLE001
        log.info("work requests unavailable: %s", type(exc).__name__)
        return None


def _default_deliberations_awaiting() -> Optional[int]:
    """Deliberation sessions finished by the agents but without any human decision (guarded; None if absent)."""
    try:
        from app.features.deliberation import store as delib_store  # guarded: deliberation workstream

        lister = getattr(delib_store, "list_", None) or getattr(delib_store, "list_sessions", None)
        if not callable(lister):
            return None
        n = 0
        for s in lister(limit=500):
            d = s.model_dump() if hasattr(s, "model_dump") else dict(s)
            if d.get("status") in ("completed", "needs_review") and not d.get("decisions"):
                n += 1
        return n
    except Exception as exc:  # noqa: BLE001
        log.info("deliberations unavailable: %s", type(exc).__name__)
        return None


def _default_human_required() -> Optional[int]:
    """Cases whose latest autonomy-policy / watchdog decision is 'requires_human' (guarded; None if absent)."""
    total: Optional[int] = None
    path = _db_path()
    if path.is_file():  # read-only SQL on the collab table (never creates it); latest decision per case
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
                if _table_exists(conn, "collab_decisions"):
                    row = conn.execute(
                        "SELECT COUNT(*) FROM (SELECT case_id, decision, MAX(rowid) FROM collab_decisions "
                        "GROUP BY case_id) WHERE decision='requires_human'").fetchone()
                    total = int(row[0])
        except sqlite3.Error as exc:
            log.info("collab decisions unavailable: %s", type(exc).__name__)
    try:  # watchdog (guarded): optional hook, else read-only probe of watchdog tables with a JSON route field
        import importlib

        wd = importlib.import_module("app.features.watchdog")
        fn = getattr(wd, "human_required_count", None)
        if callable(fn):
            total = (total or 0) + int(fn())
        elif path.is_file():
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'watchdog%'").fetchall()]
                for t in tables:
                    cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()}
                    if "json" not in cols:
                        continue
                    row = conn.execute(
                        f'SELECT COUNT(*) FROM "{t}" WHERE json_extract(json, \'$.route\')=\'human_required\' '
                        f'OR json_extract(json, \'$.routing.route\')=\'human_required\'').fetchone()
                    total = (total or 0) + int(row[0])
    except Exception:  # noqa: BLE001 - watchdog package absent or different shape
        pass
    return total


def _default_control_capabilities() -> Optional[dict]:
    try:
        from app.connectors.base import ControlSystem

        return ControlSystem().capabilities()
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Sources:
    bundle: Callable[[str], Any] = _default_bundle
    model: Callable[[], Any] = _default_model
    investigations: Callable[[], list[Any]] = _default_investigations
    work_requests: Callable[[], Optional[list[Any]]] = _default_work_requests
    count_table: Callable[[str], Optional[int]] = count_table
    deliberations_awaiting: Callable[[], Optional[int]] = _default_deliberations_awaiting
    human_required: Callable[[], Optional[int]] = _default_human_required
    control_capabilities: Callable[[], Optional[dict]] = _default_control_capabilities
    unavailable: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- data-derived sections (cached)
_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[list[Kpi], list[str]]] = {}


def _unavail(key: str, group: str, label: str, provenance: str, source: str, caveat: str, why: str) -> Kpi:
    return Kpi(key=key, group=group, label=label, value=None, provenance=provenance, source_endpoint=source,
               caveat=f"Unavailable: {why}. {caveat}", available=False)


def rolling_notable_share(residuals: np.ndarray, std_val: float, window: int = ROLL_WINDOW,
                          reference: int = ROLL_REFERENCE) -> tuple[Optional[float], int, int]:
    """Evidence-engine rule on rolling windows, vectorised: for each window of ``window`` samples, z =
    (mean residual of the window − mean residual of the ``reference`` samples preceding it) / validation residual std;
    notable when |z| >= 2. Returns (share of evaluated windows notable, n_notable, n_evaluated)."""
    r = np.asarray(residuals, dtype=float)
    n = r.size
    if std_val is None or not (std_val > 0) or n < window + reference:
        return None, 0, 0
    filled = np.where(np.isfinite(r), r, 0.0)
    cnt = np.concatenate([[0], np.cumsum(np.isfinite(r).astype(int))])
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    ends = np.arange(window + reference, n + 1)          # window = [e-window, e), reference = [e-window-reference, e-window)
    w_n = cnt[ends] - cnt[ends - window]
    r_n = cnt[ends - window] - cnt[ends - window - reference]
    ok = (w_n > 0) & (r_n > 0)
    w_mean = np.where(ok, (cs[ends] - cs[ends - window]) / np.maximum(w_n, 1), np.nan)
    r_mean = np.where(ok, (cs[ends - window] - cs[ends - window - reference]) / np.maximum(r_n, 1), np.nan)
    z = (w_mean - r_mean) / float(std_val)
    valid = np.isfinite(z)
    n_eval = int(valid.sum())
    if n_eval == 0:
        return None, 0, 0
    n_notable = int((np.abs(z[valid]) >= NOTABLE_Z).sum())
    return n_notable / n_eval, n_notable, n_eval


def _performance_and_reliability(yf, model, year: int) -> list[Kpi]:
    out: list[Kpi] = []
    src_res = "/api/planner/compressor-wash (residual series) · baseline model /api/models/evaluation"
    if model is None:
        why = "baseline model not trained"
        out.append(_unavail("tey_residual_year_mean", "performance", "Output vs expected (TEY residual, year mean)",
                            "model_derived", src_res, "Heat-rate / degradation proxy.", why))
        out.append(_unavail("compressor_wash_status", "performance", "Compressor wash (planner)", "assumption",
                            "/api/planner/compressor-wash", "Planner status with default assumptions.", why))
        out.append(_unavail("notable_deviation_share", "reliability", "Share of time with notable output deviation",
                            "model_derived", src_res, "Availability proxy.", why))
        return out
    res = np.asarray(model.residuals(yf), dtype=float)
    std_val = float(getattr(model.evaluation, "residual_std_validation", float("nan")))
    finite = res[np.isfinite(res)]
    mean_res = float(finite.mean()) if finite.size else float("nan")
    out.append(Kpi(
        key="tey_residual_year_mean", group="performance", label="Output vs expected (TEY residual, year mean)",
        value=_r(mean_res, 3), unit="MWh per hourly sample", provenance="model_derived", source_endpoint=src_res,
        caveat=("Heat-rate / degradation PROXY only: observed − expected TEY from the baseline model trained on "
                "2011–2013. The dataset has no fuel flow, so this is not a heat rate; a year-level offset also "
                "reflects model drift (2014 validation residual median is positive)."),
        detail={"n": int(finite.size), "residual_std_validation": _r(std_val, 3),
                "z_year_mean": _r(mean_res / std_val, 2) if std_val > 0 else None,
                "model_version": getattr(model, "version", None)},
    ))
    # planner: compressor wash with the planner's default assumptions
    try:
        from app.features.planner import engine as planner_engine
        from app.features.planner.schemas import CompressorWashRequest

        req = CompressorWashRequest(year=year)
        wash = planner_engine.compute_compressor_wash(yf, res, req, model_version=getattr(model, "version", None),
                                                      validation_residual_std=std_val)
        out.append(Kpi(
            key="compressor_wash_status", group="performance", label="Compressor wash (planner)",
            value=wash.status, unit="", provenance="assumption", source_endpoint="/api/planner/compressor-wash",
            caveat=("Break-even status computed with the planner's DEFAULT economic assumptions (energy price, wash "
                    "cost, outage hours, recovery fraction); change them on /planner. A planning aid, not a "
                    "maintenance instruction."),
            detail={"lost_output_rate_now_mwh_per_sample": _r(wash.lost_output_rate_now_mwh_per_sample, 3),
                    "cumulative_lost_output_mwh": _r(wash.cumulative_lost_output_mwh, 1),
                    "break_even_reached": wash.break_even_reached},
        ))
        out.append(Kpi(
            key="lost_output_rate_now", group="performance", label="Output gap to the year's best level (now)",
            value=_r(wash.lost_output_rate_now_mwh_per_sample, 3), unit="MWh per hourly sample",
            provenance="model_derived", source_endpoint="/api/planner/compressor-wash",
            caveat=("Rolling-median residual at the last sample vs the year's p95 rolling level. Fouling is one "
                    "possible cause among dispatch, ambient and model drift."),
            available=wash.lost_output_rate_now_mwh_per_sample is not None,
        ))
    except Exception as exc:  # noqa: BLE001
        out.append(_unavail("compressor_wash_status", "performance", "Compressor wash (planner)", "assumption",
                            "/api/planner/compressor-wash", "Planner status.", type(exc).__name__))
    share, n_notable, n_eval = rolling_notable_share(res, std_val)
    if share is None:
        out.append(_unavail("notable_deviation_share", "reliability", "Share of time with notable output deviation",
                            "model_derived", src_res, "Availability proxy.",
                            f"need ≥ {ROLL_WINDOW + ROLL_REFERENCE} samples and a trained model"))
    else:
        out.append(Kpi(
            key="notable_deviation_share", group="reliability", label="Share of time with notable output deviation",
            value=_r(100.0 * share, 1), unit="% of rolling windows", provenance="model_derived",
            source_endpoint=src_res,
            caveat=(f"AVAILABILITY PROXY, not availability: the evidence-engine rule (|z| ≥ {NOTABLE_Z:g} vs the "
                    f"{ROLL_REFERENCE} preceding samples, residual std from validation) applied to every rolling "
                    f"{ROLL_WINDOW}-sample window, computed in vectorised form from the baseline residual series "
                    f"(not by running the full evidence engine per window). The dataset records no outages, "
                    f"trips or availability."),
            detail={"notable_windows": n_notable, "evaluated_windows": n_eval, "window": ROLL_WINDOW,
                    "reference": ROLL_REFERENCE},
        ))
    return out


def _instruments(bundle, yf, model, year: int) -> list[Kpi]:
    from app.features.instruments import engine as inst_engine

    frame = bundle.frame
    train = frame[frame["source_year"].isin(inst_engine.TRAIN_YEARS)]
    ranges = model.evaluation.feature_ranges_train if model is not None else None
    sensors, summary = inst_engine.compute_scorecard(yf.reset_index(drop=True), train, ranges, f"year {year}")
    counts = {"ok": 0, "watch": 0, "check": 0}
    for s in sensors:
        counts[s.status] = counts.get(s.status, 0) + 1
    return [Kpi(
        key="instrument_health", group="reliability", label="Instrument health (sensors ok / watch / check)",
        value=f"{counts['ok']} / {counts['watch']} / {counts['check']}", unit="sensors",
        provenance="real", source_endpoint=f"/api/instruments/scorecard?year={year}",
        caveat=("Screening of REAL measurements with fixed heuristic thresholds (missing, out-of-range, flatline, "
                "spikes, coupling drift). 'check' means verify the transmitter first; it is not a diagnosis."),
        detail={**counts, "verify_first": list(summary.verify_first), "use_with_cross_check": list(summary.use_with_cross_check)},
    )]


def _emissions(yf, year: int, dataset_id: str) -> list[Kpi]:
    from app.features.emissions import engine as em_engine

    r = em_engine.analyze(yf, dataset_id=dataset_id, source_year=year)
    k = r.kpis
    cav = ("SCREENING ONLY on REAL CO/NOX: the default threshold is the year's own p95 (so about 5 % of hours sit "
           "above it by construction), not a permit limit. No regulatory conclusion.")
    return [
        Kpi(key="emissions_hours_above", group="compliance", label="Hours above screening threshold (CO or NOX)",
            value=int(k.hours_above_any), unit="hourly samples", provenance="real",
            source_endpoint=f"/api/emissions/overview?year={year}", caveat=cav,
            detail={"hours_above_co": k.hours_above_co, "hours_above_nox": k.hours_above_nox,
                    "rows_analyzed": k.rows_analyzed, "co_threshold": _r(r.thresholds.co, 2),
                    "nox_threshold": _r(r.thresholds.nox, 2)}),
        Kpi(key="emissions_excursions", group="compliance", label="Screening excursions (contiguous runs)",
            value=int(k.excursions_total), unit="excursions", provenance="real",
            source_endpoint=f"/api/emissions/overview?year={year}", caveat=cav,
            detail={"excursions_co": k.excursions_co, "excursions_nox": k.excursions_nox,
                    "longest_excursion_samples": k.longest_excursion_samples}),
    ]


def _thermal(bundle, year: int, n: int, dataset_id: str) -> list[Kpi]:
    from app.features.thermal import engine as th_engine
    from app.features.thermal.schemas import ThermalAssumptions

    start = max(0, n - THERMAL_WINDOW)
    frame = bundle.window(year, start, n)
    r = th_engine.evaluate(frame, dataset_id=dataset_id, year=year, start=start, end=n,
                           assumptions=ThermalAssumptions(), scenario="none", scenario_seed=42,
                           demand_multiplier=None, demand_profile="flat")
    worst = min(r.status, key=lambda s: s.margin_to_alarm_k)
    return [Kpi(
        key="thermal_min_margin", group="reliability", label="Smallest electrical thermal margin to alarm",
        value=_r(worst.margin_to_alarm_k, 1), unit="K", provenance="simulated",
        source_endpoint="/api/thermal/evaluate",
        caveat=("SIMULATED thermal model of balance-of-plant electrical assets driven by real TEY and AT with "
                f"ASSUMED ratings; latest window = samples {start}–{n - 1} of {year}. Not a measured temperature."),
        detail={"asset_id": worst.asset_id, "asset_name": worst.name, "state": worst.state,
                "window_start": start, "window_end": n,
                "assets_below_rule": [s.asset_id for s in r.status if s.margin_to_alarm_k < THERMAL_MARGIN_RULE_K]},
    )]


def _grid(bundle, year: int) -> list[Kpi]:
    from app import services
    from app.features.grid import readiness as rd

    g = rd.compute_readiness(bundle, year, None, None, rd.DEFAULT_NAMEPLATE_MW, rd.DEFAULT_H_S, rd.DEFAULT_PF,
                             computed_at_utc=services.now_utc())
    head = g.numbers.get("headroom_to_nameplate")
    return [Kpi(
        key="grid_headroom", group="grid", label="Grid readiness: output headroom to nameplate (proxy)",
        value=_r(head.value if head else None, 1), unit="MWh/h (proxy)", provenance="assumption",
        source_endpoint=f"/api/grid/readiness?year={year}",
        caveat=(f"Nameplate {rd.DEFAULT_NAMEPLATE_MW:g} MW is an ASSUMPTION; headroom = nameplate − year-mean TEY "
                "(MWh per hourly sample used as an output proxy). Grid-services revenue is not computed."),
        available=head is not None and head.value is not None,
        detail={"readiness_status": g.summary.status, "readiness_headline": g.summary.headline},
    )]


def _data_kpis(dataset_id: str, year: int, src: Sources) -> list[Kpi]:
    model = src.model()
    try:
        bundle = src.bundle(dataset_id)
    except Exception as exc:  # noqa: BLE001
        src.unavailable.append(f"dataset {dataset_id}: {type(exc).__name__}")
        return []
    if int(year) not in bundle.years():
        raise ValueError(f"year {year} not in dataset {dataset_id} (available: {', '.join(map(str, bundle.years()))})")
    key = (dataset_id, int(year), len(bundle.frame), getattr(model, "version", None),
           getattr(getattr(model, "evaluation", None), "trained_at_utc", None), id(src.bundle))
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        src.unavailable.extend(hit[1])
        return [k.model_copy(deep=True) for k in hit[0]]
    yf = bundle.year_frame(int(year))
    out: list[Kpi] = []
    n_unavail = len(src.unavailable)
    for name, fn in (("performance", lambda: _performance_and_reliability(yf, model, year)),
                     ("instruments", lambda: _instruments(bundle, yf, model, year)),
                     ("thermal", lambda: _thermal(bundle, year, len(yf), dataset_id)),
                     ("emissions", lambda: _emissions(yf, year, dataset_id)),
                     ("grid", lambda: _grid(bundle, year))):
        try:
            out += fn()
        except Exception as exc:  # noqa: BLE001 - one engine failing must not hide the others
            log.warning("executive section %s failed: %s", name, type(exc).__name__)
            src.unavailable.append(f"{name}: {type(exc).__name__}")
    with _cache_lock:
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = ([k.model_copy(deep=True) for k in out], list(src.unavailable[n_unavail:]))
    return out


# ----------------------------------------------------------------------------- store-derived sections (live)
def _decisions_people_safety(src: Sources) -> tuple[list[Kpi], list[OpenCase]]:
    out: list[Kpi] = []
    try:
        invs = list(src.investigations())
    except Exception as exc:  # noqa: BLE001
        invs = []
        src.unavailable.append(f"investigations: {type(exc).__name__}")
    awaiting = [i for i in invs if i.review is None or i.review.decision == "more_data_requested"]
    open_cases = [OpenCase(case_id=i.case_id, scenario_id=i.scenario.scenario_id,
                           synthetic=bool(i.scenario.synthetic or i.scenario_label == "synthetic_overlay"),
                           status=i.status, severity=(i.report.severity if i.report else None))
                  for i in sorted(awaiting, key=lambda i: i.created_at_utc, reverse=True)[:10]]
    out.append(Kpi(key="cases_awaiting_review", group="decisions", label="Investigation cases awaiting human review",
                   value=len(awaiting), unit="cases", provenance="prototype_metric",
                   source_endpoint="/api/investigations",
                   caveat="Counts stored prototype cases (demo and synthetic-overlay included), not plant events.",
                   detail={"cases_total": len(invs)}))
    wrs = src.work_requests()
    if wrs is None:
        out.append(_unavail("work_requests_open", "decisions", "Work requests open", "prototype_metric",
                            "/api/plant/work-requests", "Simulated routing.", "plant-ops module unavailable"))
    else:
        n_open = sum(1 for w in wrs if getattr(w, "status", None) in ("open", "acknowledged"))
        out.append(Kpi(key="work_requests_open", group="decisions", label="Work requests open",
                       value=n_open, unit="requests", provenance="prototype_metric",
                       source_endpoint="/api/plant/work-requests",
                       caveat="Routed in-app with SIMULATED notifications; no CMMS or email system is touched.",
                       detail={"total": len(wrs)}))
    delib = src.deliberations_awaiting()
    out.append(Kpi(key="deliberations_awaiting", group="decisions", label="Deliberations awaiting a human decision",
                   value=delib, unit="sessions", provenance="prototype_metric",
                   source_endpoint="/api/deliberation (if installed)", available=delib is not None,
                   caveat=("Multi-agent deliberations on proposed changes that are finished but not yet decided by a "
                           "person." if delib is not None else "Unavailable: deliberation module not installed.")))
    hr = src.human_required()
    out.append(Kpi(key="human_required", group="decisions", label="Watchdog / triage items requiring a human",
                   value=hr, unit="cases", provenance="prototype_metric",
                   source_endpoint="/api/collab (autonomy policy) · watchdog (if installed)", available=hr is not None,
                   caveat=("Latest autonomy-policy decision per case is 'requires_human'." if hr is not None
                           else "Unavailable: collab / watchdog modules not installed.")))
    try:
        from app.features.ops.metrics import compute_metrics

        m = compute_metrics(invs)
        out.append(Kpi(key="investigation_wall_time", group="decisions",
                       label="Median investigation wall time (live Meta cases)",
                       value=_r(m.live_wall_time_s.median, 1), unit="s", provenance="prototype_metric",
                       source_endpoint="/api/ops/metrics", available=m.live_wall_time_s.median is not None,
                       caveat=(f"First model request to accepted report, over {m.live_wall_time_s.n} live case(s) in "
                               "this prototype store. Not engineer time and not a plant measurement."),
                       detail={"n": m.live_wall_time_s.n}))
        fp = m.validator_first_pass_acceptance
        out.append(Kpi(key="first_pass_acceptance", group="decisions",
                       label="Validator first-pass acceptance (live Meta reports)",
                       value=_r(100.0 * fp.rate, 1) if fp.rate is not None else None, unit="%",
                       provenance="prototype_metric", source_endpoint="/api/ops/metrics", available=fp.rate is not None,
                       caveat=(f"{fp.numerator} of {fp.n} validated live reports passed the provenance/safety "
                               "validator without a rewrite. Measures form and provenance, not diagnostic accuracy."),
                       detail={"numerator": fp.numerator, "n": fp.n}))
        cr = m.cited_ids_resolving
        out.append(Kpi(key="cited_ids_resolving", group="safety", label="Cited evidence IDs that resolve",
                       value=_r(100.0 * cr.rate, 1) if cr.rate is not None else None, unit="%",
                       provenance="prototype_metric", source_endpoint="/api/ops/metrics", available=cr.rate is not None,
                       caveat=(f"{cr.numerator} of {cr.n} evidence IDs cited in stored reports exist in their case. "
                               "The validator rejects reports that cite unknown evidence."),
                       detail={"numerator": cr.numerator, "n": cr.n}))
    except Exception as exc:  # noqa: BLE001
        src.unavailable.append(f"ops metrics: {type(exc).__name__}")
    # people & knowledge
    precedents = sum(1 for i in invs if i.review is not None and i.review.decision in REVIEWED)
    out.append(Kpi(key="precedents", group="people_knowledge", label="Reviewed precedents on file",
                   value=precedents, unit="cases", provenance="prototype_metric",
                   source_endpoint="/api/plant/precedents",
                   caveat="Cases with a recorded human review that precedent recall can reuse. Prototype store only."))
    for key, label, table, src_ep, cav in (
        ("handover_notes", "Shift handover notes drafted", "handover_notes", "/api/ops/handover",
         "Drafts requiring shift-supervisor sign-off; count is of drafts, not of signed handovers."),
        ("onboarding_briefs", "Onboarding briefs drafted", "onboarding_briefs", "/api/collab (if installed)",
         "Persona onboarding briefs drafted by the collaboration layer."),
    ):
        n = src.count_table(table)
        out.append(Kpi(key=key, group="people_knowledge", label=label, value=n, unit="drafts",
                       provenance="prototype_metric", source_endpoint=src_ep, available=n is not None,
                       caveat=cav if n is not None else f"Unavailable: table '{table}' not present yet. {cav}"))
    # safety posture
    caps = src.control_capabilities()
    if caps is None:
        out.append(_unavail("control_write_path", "safety", "Control-system write path", "prototype_metric",
                            "/api/connectors/status", "By design there is none.", "connectors module unavailable"))
    else:
        has_write = bool(caps.get("write")) or bool(caps.get("read"))
        out.append(Kpi(key="control_write_path", group="safety", label="Control-system write path",
                       value="present" if has_write else "none", unit="", provenance="prototype_metric",
                       source_endpoint="/api/connectors/status",
                       caveat=("Control-system connector reports read=False, write=False: no PLC/DCS/SCADA path. "
                               "Historian, CMMS and notifier connectors are SIMULATED. Not an OT-security audit."),
                       detail={"read": bool(caps.get("read")), "write": bool(caps.get("write"))}))
    return out, open_cases


# ----------------------------------------------------------------------------- attention rules
def _item(id_: str, severity: str, title: str, detail: str, persona: str, link: str, rule: str,
          kpi_keys: list[str], case_ids: Optional[list[str]] = None) -> AttentionItem:
    return AttentionItem(id=id_, severity=severity, title=title, detail=detail, persona=persona,
                         persona_name=PERSONA_NAMES.get(persona, persona), link=link, rule=rule,
                         kpi_keys=kpi_keys, case_ids=case_ids or [])


def attention_rules(kpis: list[Kpi], open_cases: list[OpenCase]) -> list[AttentionItem]:
    """Deterministic rules over the KPIs. Each item names the responsible persona and the page to open."""
    by = {k.key: k for k in kpis}
    items: list[AttentionItem] = []
    th = by.get("thermal_min_margin")
    if th and th.available and isinstance(th.value, (int, float)) and th.value < THERMAL_MARGIN_RULE_K:
        items.append(_item("thermal_margin", "attention",
                           f"Electrical thermal margin {th.value:g} K to alarm on {th.detail.get('asset_name', 'an asset')}",
                           "Simulated model on real load; confirm with site thermography / ratings before any action.",
                           "electrical_engineer", "/thermal", f"thermal margin to alarm < {THERMAL_MARGIN_RULE_K:g} K",
                           ["thermal_min_margin"]))
    wash = by.get("compressor_wash_status")
    if wash and wash.available and isinstance(wash.value, str) and wash.value.startswith("consider"):
        items.append(_item("compressor_wash", "attention", "Planner: consider scheduling a compressor wash",
                           "Break-even reached under default assumptions; timing is a human decision.",
                           "performance_engineer", "/planner", "planner wash status = consider scheduling",
                           ["compressor_wash_status"]))
    inst = by.get("instrument_health")
    if inst and inst.available and int(inst.detail.get("check", 0) or 0) > 0:
        sensors = ", ".join(inst.detail.get("verify_first") or [])
        items.append(_item("instrument_check", "attention",
                           f"{inst.detail.get('check')} sensor(s) flagged 'check': {sensors}",
                           "Verify the transmitter before trusting conclusions that depend on it.",
                           "ic_engineer", "/instruments", "instrument scorecard status = check", ["instrument_health"]))
    hr = by.get("human_required")
    if hr and hr.available and isinstance(hr.value, int) and hr.value > 0:
        items.append(_item("human_required", "attention", f"{hr.value} triage item(s) require a human decision",
                           "The autonomy policy / watchdog escalated these cases to a person.",
                           "reliability_engineer", "/watchdog", "watchdog / triage human_required > 0",
                           ["human_required"]))
    dl = by.get("deliberations_awaiting")
    if dl and dl.available and isinstance(dl.value, int) and dl.value > 0:
        items.append(_item("deliberations", "attention", f"{dl.value} deliberation(s) awaiting a decision",
                           "Agents finished; a named person must accept or reject.",
                           "plant_manager", "/propose", "deliberations awaiting decision > 0", ["deliberations_awaiting"]))
    wr = by.get("work_requests_open")
    if wr and wr.available and isinstance(wr.value, int) and wr.value > 0:
        items.append(_item("work_requests", "info", f"{wr.value} work request(s) open",
                           "Routed to named engineers (simulated notifications).",
                           "shift_supervisor", "/inbox", "open work requests > 0", ["work_requests_open"]))
    cr = by.get("cases_awaiting_review")
    if cr and isinstance(cr.value, int) and cr.value > 0:
        items.append(_item("cases_awaiting", "info", f"{cr.value} investigation case(s) awaiting human review",
                           "Draft reports need an engineer's accept / reject.", "reliability_engineer",
                           "/investigations", "cases awaiting review > 0", ["cases_awaiting_review"],
                           [c.case_id for c in open_cases[:5]]))
    em = by.get("emissions_excursions")
    if em and em.available and isinstance(em.value, int) and em.value > 0:
        items.append(_item("emissions", "info", f"{em.value} emissions screening excursion(s) in the year",
                           "Screening against the year's own p95, not a permit limit.",
                           "environmental_engineer", "/emissions", "emissions screening excursions > 0",
                           ["emissions_hours_above", "emissions_excursions"]))
    items.sort(key=lambda i: 0 if i.severity == "attention" else 1)
    return items


METHOD_NOTES = [
    "Every KPI is computed by an existing ThermoMind engine or counted from an existing table; see source_endpoint.",
    "Provenance: real = public UCI measurements; model_derived = baseline-model residuals; simulated = thermal model; "
    "assumption = depends on default assumptions; prototype_metric = this prototype's own store.",
    "UCI data has no timestamps; 'latest window' means the last samples of the source year.",
    "No financial outcome, saving or availability figure is claimed.",
]


def compute_overview(year: int = 2014, dataset_id: str = DEFAULT_DATASET_ID,
                     sources: Optional[Sources] = None, now_utc: Optional[str] = None) -> ExecutiveOverview:
    src = sources or Sources()
    src.unavailable = []
    kpis = _data_kpis(dataset_id, year, src)
    k2, open_cases = _decisions_people_safety(src)
    kpis += k2
    if now_utc is None:
        from app import services

        now_utc = services.now_utc()
    return ExecutiveOverview(dataset_id=dataset_id, year=int(year), computed_at_utc=now_utc,
                             attention=attention_rules(kpis, open_cases), kpis=kpis, open_cases=open_cases,
                             sources_unavailable=list(src.unavailable), method_notes=list(METHOD_NOTES))
