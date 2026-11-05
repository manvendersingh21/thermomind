"""Deterministic pre-checks ("constraint findings") for a proposed change. Numbers only from running code.

Every finding is numbered and carries provenance + the module that produced it:
  1. basis of the comparison (real rows of the window; association label)
  2. primary-delta sensitivity (``app.plant.sensitivity.simulate_change``: model ΔTEY, OOD flag)
  3. joint model check (all model-input deltas applied together to the real rows; baseline model ΔTEY)
  4. implied deltas vs training range (OOD flags per implied measurement)
  5. TIT vs the training-years p99 envelope (``features.grid.readiness.training_stats``)
  6. emissions screening vs the year p95 of CO / NOx (``features.emissions.engine.p95``)
  7. electrical thermal margins at the implied load (``features.thermal.engine.evaluate``, demand multiplier)
  8. grid-readiness headroom (``features.grid.readiness.compute_readiness``; nameplate is an assumption)
Unavailable checks are reported as ``status="unavailable"`` with the reason, never silently dropped.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from app.features.deliberation.schemas import ConstraintFinding, ModelledChange, ProposeRequest
from app.plant.schemas import ASSOCIATION_LABEL
from app.plant.sensitivity import BaseWindow, resolve_base, simulate_change, train_range_check
from app.schemas import FEATURE_KEYS, MEASUREMENTS

log = logging.getLogger("thermomind.deliberation.prechecks")
WEAK_R = 0.3
STATUS_RANK = {"ok": 0, "info": 0, "unavailable": 0, "watch": 1, "concern": 2, "exceeds": 3}


def _r(x: Any, nd: int = 3) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def _bundle(dataset_id: str) -> Any:
    from app import services

    try:
        return services.get_repo().get(dataset_id)
    except KeyError:
        if not services.seed_uci_if_available():
            raise
        return services.get_repo().get(dataset_id)


def resolve_window(req: ProposeRequest) -> BaseWindow:
    """Case window, explicit year/start/end, or the default demo window. KeyError -> 404, ValueError -> 422."""
    if req.case_id:
        return resolve_base(req.case_id)
    given = [v is not None for v in (req.year, req.start, req.end)]
    if not any(given):
        return resolve_base(None)
    if not all(given):
        raise ValueError("give case_id, or all of year/start/end (or none of them for the default window)")
    if req.end <= req.start:
        raise ValueError(f"end ({req.end}) must be greater than start ({req.start})")
    if req.end - req.start < 24:
        raise ValueError("window must contain at least 24 rows")
    if req.end - req.start > 9000:
        raise ValueError("window must contain at most 9000 rows")
    bundle = _bundle(req.dataset_id)  # KeyError -> 404
    try:
        bundle.window(req.year, req.start, req.end)
    except IndexError as exc:
        raise ValueError(str(exc)) from None
    return BaseWindow(req.dataset_id, int(req.year), int(req.start), int(req.end), None,
                      f"real observed rows of {req.year}, samples {req.start}–{req.end - 1}")


OOD_CONCERN_SHARE = 0.25


def _ood_status(outside: int, rows: int) -> str:
    """Rows outside the training range: none -> ok, a few -> watch, >= 25 % of the window -> concern."""
    if not outside:
        return "ok"
    return "concern" if rows and outside / rows >= OOD_CONCERN_SHARE else "watch"


def _delta(change: ModelledChange, m: str) -> float:
    return float(sum(d.delta for d in change.deltas if d.measurement == m))


class _Builder:
    def __init__(self) -> None:
        self.items: list[ConstraintFinding] = []

    def add(self, key: str, title: str, status: str, detail: str, provenance: str, source: str,
            **numbers: Any) -> None:
        self.items.append(ConstraintFinding(n=len(self.items) + 1, key=key, title=title, status=status,
                                            detail=detail[:1200], provenance=provenance, source=source,
                                            numbers={k: v for k, v in numbers.items() if v is not None}))

    def guarded(self, key: str, title: str, source: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a failing check is reported, never hidden
            log.info("pre-check %s unavailable: %s", key, type(exc).__name__)
            self.add(key, title, "unavailable", f"check unavailable ({type(exc).__name__}: {str(exc)[:200]})",
                     "derived_from_history", source)


def run_prechecks(change: ModelledChange, base: BaseWindow, model: Any = None) -> list[ConstraintFinding]:
    from app import services

    model = model if model is not None else services.get_model()
    bundle = _bundle(base.dataset_id)
    window = bundle.window(base.year, base.start, base.end)
    n = len(window)
    b = _Builder()
    rng = f"{base.year} samples {base.start}–{base.end - 1} (n={n})"

    b.add("basis", "Basis of every number below", "info",
          f"Computed on the {base.basis}: {rng}. Rows are hourly samples without timestamps. Implied deltas are "
          f"{ASSOCIATION_LABEL}. Model effects are ceteris-paribus sensitivities of the statistical baseline.",
          "real_observation", "app.plant.sensitivity.resolve_base", rows=n, case_id=base.case_id)

    if not change.observable or not change.deltas:
        b.add("observability", "Observability of the proposed change", "unavailable",
              " ".join(change.qualitative_notes)[:600] or "Not observable in this data; qualitative only.",
              "not_observable", "app.features.deliberation.intents")

    primary = next((d for d in change.deltas if d.role == "primary"), None)
    sens_cache: dict[str, dict] = {}

    def _sens(m: str, d: float) -> dict:
        if m not in sens_cache:
            sens_cache[m] = simulate_change(m, d, base, model)
        return sens_cache[m]

    # 2. primary delta sensitivity
    for d in [x for x in change.deltas if x.role == "primary"]:
        def _primary(d=d) -> None:
            s = _sens(d.measurement, d.delta)
            me, trc = s["model_effect"], s["train_range_check"]
            parts = [f"{d.measurement} {d.delta:+g} {d.unit} on the real rows: perturbed range "
                     f"{trc['perturbed_min']}..{trc['perturbed_max']} vs training range "
                     f"[{trc['train_min']}, {trc['train_max']}] ({trc['basis']}); "
                     f"{trc['rows_outside']}/{trc['rows']} rows outside."]
            if me.get("applicable"):
                parts.append(f"Baseline model expected TEY {me['delta_tey_mean']:+.3f} MWh on average "
                             f"(row range {me['delta_tey_min']:+.3f}..{me['delta_tey_max']:+.3f}).")
            else:
                parts.append(me.get("note") or "no model effect")
            status = _ood_status(trc["rows_outside"], trc["rows"])
            b.add(f"sensitivity_{d.measurement}", f"Sensitivity: {d.measurement} {d.delta:+g} {d.unit}", status,
                  " ".join(parts), "model_derived" if me.get("applicable") else "derived_from_history",
                  "app.plant.sensitivity.simulate_change",
                  delta_tey_mean=me.get("delta_tey_mean"), rows_outside=trc["rows_outside"], rows=trc["rows"],
                  ood_flag=trc["ood_flag"], train_min=trc["train_min"], train_max=trc["train_max"])
        b.guarded(f"sensitivity_{d.measurement}", f"Sensitivity: {d.measurement}", "app.plant.sensitivity", _primary)

    # 3. joint model check (all model-input deltas together)
    feats = getattr(model, "features", FEATURE_KEYS) if model is not None else FEATURE_KEYS
    joint = {d.measurement: d.delta for d in change.deltas if d.measurement in feats}
    if joint and model is not None:
        def _joint() -> None:
            pert = window.copy()  # never mutate repository rows
            for m, dv in joint.items():
                pert[m] = pert[m].astype(float) + dv
            dd = np.asarray(model.predict(pert)) - np.asarray(model.predict(window))
            mean = float(np.nanmean(dd))
            intended = _delta(change, "TEY") if primary is not None and primary.measurement == "TEY" else None
            detail = (f"All model-input deltas applied together ({', '.join(f'{k} {v:+.3g}' for k, v in joint.items())}"
                      f"): baseline model expected TEY {mean:+.3f} MWh on average "
                      f"(row range {np.nanmin(dd):+.3f}..{np.nanmax(dd):+.3f}).")
            status = "info"
            if intended:
                ratio = mean / intended if intended else None
                detail += (f" Intended TEY change {intended:+g} MWh; the model reproduces "
                           f"{100 * ratio:.0f}% of it from the implied conditions." if ratio is not None else "")
                if ratio is not None and (ratio < 0.5 or ratio > 1.5):
                    status = "watch"
                    detail += (" The statistical baseline does not reproduce the intended output from the implied "
                               "conditions; treat the implied deltas with caution (tree model is flat outside the "
                               "training range).")
            b.add("joint_model", "Joint model check (implied conditions → expected TEY)", status, detail,
                  "model_derived", "baseline model predict() on perturbed copies of the real rows",
                  delta_tey_mean=_r(mean), delta_tey_min=_r(np.nanmin(dd)), delta_tey_max=_r(np.nanmax(dd)),
                  intended_delta_tey=intended, model_version=getattr(model, "version", None))
        b.guarded("joint_model", "Joint model check", "baseline model", _joint)

    # 4. implied deltas vs training range
    implied = [d for d in change.deltas if d.role == "implied"]
    if implied:
        def _implied() -> None:
            rows, outside, weak, worst = [], [], [], "ok"
            for d in implied:
                trc = train_range_check(d.measurement, d.delta, window, model, base.dataset_id)
                rows.append({"measurement": d.measurement, "delta": d.delta, "unit": d.unit, "r": d.pearson_r,
                             "rows_outside": trc["rows_outside"], "train_max": trc["train_max"],
                             "perturbed_max": trc["perturbed_max"]})
                st = _ood_status(trc["rows_outside"], trc["rows"])
                if STATUS_RANK[st] > STATUS_RANK[worst]:
                    worst = st
                if trc["ood_flag"]:
                    outside.append(f"{d.measurement} ({trc['rows_outside']}/{trc['rows']} rows)")
                if d.pearson_r is not None and abs(d.pearson_r) < WEAK_R:
                    weak.append(f"{d.measurement} (r={d.pearson_r:+.2f})")
            detail = ("Implied: " + "; ".join(f"{x['measurement']} {x['delta']:+.3g} {x['unit']}" for x in rows) + ". ")
            detail += ("Outside the training range: " + ", ".join(outside) + ". ") if outside else \
                "All implied values stay within the training range. "
            if weak:
                detail += "Weak associations (|r| < 0.3, little predictive value): " + ", ".join(weak) + "."
            b.add("implied_range", "Implied deltas vs training range", worst, detail,
                  "statistical_association", "app.plant.sensitivity.train_range_check", items=rows)
        b.guarded("implied_range", "Implied deltas vs training range", "app.plant.sensitivity", _implied)

    # 5. TIT envelope
    def _tit() -> None:
        from app.features.grid.readiness import training_stats as grid_stats

        ts = grid_stats(bundle.frame)
        tit = pd.to_numeric(window["TIT"], errors="coerce").to_numpy(float)
        wmax = float(np.nanmax(tit))
        dt = _delta(change, "TIT")
        new_max = wmax + dt
        p99, tmax = ts.tit_p99, ts.tit_max
        if p99 is None:
            raise ValueError("no TIT training statistics")
        if tmax is not None and new_max > tmax + 1e-9:
            status = "exceeds"
        elif new_max > p99 + 1e-9:
            status = "concern"
        elif p99 - new_max < 2.0:
            status = "watch"
        else:
            status = "ok"
        b.add("tit_envelope", "TIT vs training-years p99 envelope", status,
              f"Window max TIT {wmax:.1f} °C {format(dt, '+.1f') + ' °C implied = ' + format(new_max, '.1f') + ' °C' if dt else '(no TIT change modelled)'}"
              f" vs historical p99 {p99:.1f} °C and max {tmax:.1f} °C over {ts.years}. Margin to p99 "
              f"{p99 - new_max:+.1f} °C. Historical envelope, not an OEM limit; TIT clusters at its ceiling at base "
              f"load (temperature-controlled operation), so a margin near zero means 'at the usual ceiling'.",
              "derived_from_history", "app.features.grid.readiness.training_stats",
              window_max_c=_r(wmax, 1), delta_tit_c=_r(dt, 2), new_max_c=_r(new_max, 1), p99_c=_r(p99, 1),
              max_c=_r(tmax, 1), margin_to_p99_c=_r(p99 - new_max, 1))
    b.guarded("tit_envelope", "TIT vs training-years p99 envelope", "app.features.grid.readiness", _tit)

    # 6. emissions screening
    def _emissions() -> None:
        from app.features.emissions.engine import p95

        yf = bundle.year_frame(base.year)
        parts, statuses, nums = [], [], {}
        for m in ("CO", "NOX"):
            thr = p95(yf[m])
            if thr is None:
                continue
            v = pd.to_numeric(window[m], errors="coerce").to_numpy(float)
            dv = _delta(change, m)
            before = float(np.mean(v > thr))
            after = float(np.mean(v + dv > thr))
            wp95 = float(np.nanpercentile(v, 95))
            st = "ok"
            if after > before + 0.05 or float(np.nanmean(v)) + dv > thr:
                st = "concern"
            elif before >= 0.2 or wp95 >= 0.9 * thr:
                st = "watch"
            statuses.append(st)
            parts.append(f"{m}: screening threshold {thr:.2f} {MEASUREMENTS[m]['unit']} (p95 of {base.year}); window "
                         f"mean {np.nanmean(v):.2f}, window p95 {wp95:.2f}; {100 * before:.0f}% of samples above now"
                         + (f", {100 * after:.0f}% after the implied {dv:+.3g}" if dv else ", no change implied"))
            nums[m] = {"threshold": _r(thr), "window_mean": _r(np.nanmean(v)), "window_p95": _r(wp95),
                       "share_above_before": _r(before), "share_above_after": _r(after), "implied_delta": _r(dv)}
        if not parts:
            raise ValueError("no CO/NOX values")
        order = ["ok", "watch", "concern"]
        status = max(statuses, key=order.index)
        b.add("emissions", "Emissions screening (CO / NOx vs year p95)", status,
              "; ".join(parts) + ". Screening threshold = p95 of this year, not a permit limit; implied shifts are "
              "association (NOx vs load is weak in this data).", "derived_from_history",
              "app.features.emissions.engine.p95", **nums)
    b.guarded("emissions", "Emissions screening", "app.features.emissions.engine", _emissions)

    # 7. electrical thermal margins at the implied load
    dtey = _delta(change, "TEY")
    if dtey:
        def _thermal() -> None:
            from app.features.thermal import engine as th

            tey_mean = float(pd.to_numeric(window["TEY"], errors="coerce").mean())
            mult = (tey_mean + dtey) / tey_mean
            clamped = min(2.0, max(0.5, mult))
            res = th.evaluate(window, dataset_id=base.dataset_id, year=base.year, start=base.start, end=base.end,
                              demand_multiplier=clamped)
            st_by = {s.asset_id: s for s in res.demand.scenario_status}
            rows, worst = [], "ok"
            appr = res.assumptions.approach_margin_k
            for r in res.demand.impact:
                s = st_by.get(r.asset_id)
                margin = (s.alarm_c - r.scenario_peak_c) if s else None
                rows.append({"asset": r.asset_id, "baseline_peak_c": r.baseline_peak_c,
                             "scenario_peak_c": r.scenario_peak_c, "delta_peak_k": r.delta_peak_k,
                             "alarm_c": s.alarm_c if s else None, "margin_to_alarm_k": _r(margin, 1),
                             "samples_above_alarm": r.scenario_samples_above_alarm,
                             "samples_above_limit": r.scenario_samples_above_limit})
                if r.scenario_samples_above_limit > 0:
                    worst = "exceeds"
                elif r.scenario_samples_above_alarm > r.baseline_samples_above_alarm and worst != "exceeds":
                    worst = "concern"
                elif margin is not None and margin < appr and worst == "ok":
                    worst = "watch"
            tight = min(rows, key=lambda x: x["margin_to_alarm_k"] if x["margin_to_alarm_k"] is not None else 1e9)
            b.add("thermal_margins", "Electrical thermal margins at the implied load", worst,
                  f"Demand multiplier (TEY mean {tey_mean:.2f} {dtey:+g}) / {tey_mean:.2f} = {mult:.4f}"
                  f"{' (clamped to ' + format(clamped, '.2f') + ')' if clamped != mult else ''}. Tightest asset "
                  f"{tight['asset']}: peak {tight['baseline_peak_c']:.1f} → {tight['scenario_peak_c']:.1f} °C, margin "
                  f"to alarm {tight['margin_to_alarm_k']} K. SIMULATED thermal feed from real load + ambient with "
                  f"default planning assumptions (ratings are assumptions, not nameplate data).",
                  "simulated", "app.features.thermal.engine.evaluate(demand_multiplier)",
                  demand_multiplier=_r(mult, 4), assets=rows,
                  loss_of_life_pct_baseline=res.demand.baseline_loss_of_life_pct,
                  loss_of_life_pct_scenario=res.demand.scenario_loss_of_life_pct)
        b.guarded("thermal_margins", "Electrical thermal margins", "app.features.thermal.engine", _thermal)

        # 8. grid readiness headroom
        def _grid() -> None:
            from app.features.grid.readiness import compute_readiness

            gr = compute_readiness(bundle, base.year, base.start, base.end)
            head = gr.numbers.get("headroom_to_nameplate")
            tmax = gr.numbers.get("tey_max_train")
            tey = pd.to_numeric(window["TEY"], errors="coerce").to_numpy(float)
            new_peak = float(np.nanmax(tey)) + dtey
            status = "ok"
            if head is not None and head.value is not None and dtey > head.value:
                status = "exceeds"
            elif tmax is not None and tmax.value is not None and new_peak > tmax.value:
                status = "concern"
            elif head is not None and head.value is not None and dtey > 0.5 * head.value:
                status = "watch"
            b.add("grid_headroom", "Grid-readiness headroom (output proxy)", status,
                  f"Headroom to nameplate {head.value if head else 'n/a'} (nameplate {gr.assumptions.nameplate_mw:g} "
                  f"MW is an ASSUMPTION, not from the dataset) vs the proposed {dtey:+g}; window peak TEY + change = "
                  f"{new_peak:.2f} vs historical max {tmax.value if tmax else 'n/a'} MWh. TEY is an output proxy "
                  f"(MWh per hourly sample).", "assumption", "app.features.grid.readiness.compute_readiness",
                  headroom_to_nameplate=head.value if head else None, nameplate_mw=gr.assumptions.nameplate_mw,
                  tey_max_train=tmax.value if tmax else None, new_peak_tey=_r(new_peak, 2))
        b.guarded("grid_headroom", "Grid-readiness headroom", "app.features.grid.readiness", _grid)
    return b.items


def worst_status(findings: list[ConstraintFinding]) -> str:
    return max((f.status for f in findings), key=lambda s: STATUS_RANK[s], default="ok")
