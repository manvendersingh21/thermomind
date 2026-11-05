"""Operator intents -> modelled measurement deltas on the base window.

Each intent maps to ONE primary measurement delta (what the operator says they want) plus implied deltas of
coupled measurements. Implied deltas use least-squares slopes (cov/var) over the 2011–2013 training years of
this plant's data, via ``app.plant.sensitivity.training_stats`` — a statistical association, not causation and
not physics. Quantities the UCI data does not measure (fuel flow, IGV angle, cooling water) are named as
qualitative notes and never given a number.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from app.features.deliberation.schemas import (SLOPE_LABEL, CustomIntent, IntentInfo, MagnitudeSpec,
                                               MeasurementDelta, ModelledChange)
from app.schemas import MEASUREMENT_KEYS, MEASUREMENTS

DEFAULT_DATASET = "ds_uci_551"
TEY_NOTE = ("TEY is energy per hourly sample (MWh, as published). A sustained +X MW over an hour is modelled as "
            "+X MWh per hourly sample; TEY is never converted.")
FUEL_NOTE = "Fuel flow is not measured in this dataset: a higher fuel demand is expected qualitatively, no number."

# implied: measurements whose delta follows from the primary one via the training-year slope
INTENTS: list[dict[str, Any]] = [
    {"intent_id": "raise_output", "label": "Raise output by X MW",
     "description": "More electricity: the unit would carry more load (TEY up). Firing temperature, compressor "
                    "pressure and exhaust back-pressure historically rise with load.",
     "magnitude": {"unit": "MW", "default": 5.0, "min": 0.5, "max": 20.0, "step": 0.5,
                   "label": "Additional output (MW, modelled as MWh per hourly sample)"},
     "primary": "TEY", "sign": +1, "implied": ["TIT", "CDP", "GTEP", "TAT", "AFDP", "CO", "NOX"],
     "subsystems": ["generator_output", "combustion_turbine", "compressor", "exhaust_emissions", "intake"],
     "notes": [TEY_NOTE, FUEL_NOTE]},
    {"intent_id": "lower_output", "label": "Lower output by X MW",
     "description": "Less electricity: the unit would carry less load (TEY down); part-load operation shifts "
                    "temperatures and emissions.",
     "magnitude": {"unit": "MW", "default": 5.0, "min": 0.5, "max": 20.0, "step": 0.5,
                   "label": "Output reduction (MW, modelled as MWh per hourly sample)"},
     "primary": "TEY", "sign": -1, "implied": ["TIT", "CDP", "GTEP", "TAT", "AFDP", "CO", "NOX"],
     "subsystems": ["generator_output", "combustion_turbine", "compressor", "exhaust_emissions"],
     "notes": [TEY_NOTE, "Part-load CO behaviour is captured only as historical association."]},
    {"intent_id": "open_igv_airflow", "label": "Open inlet guide vanes / increase airflow",
     "description": "More air through the compressor. IGV angle and air mass flow are not measured; the change is "
                    "expressed as a compressor discharge pressure rise (CDP) with a slight filter ΔP rise (AFDP).",
     "magnitude": {"unit": MEASUREMENTS["CDP"]["unit"], "default": 0.3, "min": 0.1, "max": 2.0, "step": 0.1,
                   "label": "Compressor discharge pressure rise (CDP, unit as published)"},
     "primary": "CDP", "sign": +1, "implied": ["AFDP", "TEY"],
     "subsystems": ["compressor", "intake", "combustion_turbine", "generator_output"],
     "notes": ["IGV position and air mass flow are not in the dataset; CDP is used as the observable proxy.",
               "CDP unit is 'mbar' as published and is under validation."]},
    {"intent_id": "raise_firing_temperature", "label": "Raise firing temperature by X °C",
     "description": "Hotter combustion (TIT up). Output historically rises with TIT; hot-gas-path parts and NOx "
                    "are the usual concerns.",
     "magnitude": {"unit": "°C", "default": 5.0, "min": 1.0, "max": 30.0, "step": 1.0,
                   "label": "Turbine inlet temperature rise (°C)"},
     "primary": "TIT", "sign": +1, "implied": ["TEY", "TAT", "CDP", "CO", "NOX"],
     "subsystems": ["combustion_turbine", "generator_output", "exhaust_emissions"],
     "notes": ["TIT is a derived/controlled temperature in this dataset; the training p99 envelope is "
               "historical, not an OEM limit.", FUEL_NOTE]},
    {"intent_id": "run_with_higher_filter_dp", "label": "Run with filter ΔP higher (defer filter change)",
     "description": "Keep running while the intake filters load further (AFDP up), e.g. deferring a filter change.",
     "magnitude": {"unit": "mbar", "default": 0.5, "min": 0.1, "max": 3.0, "step": 0.1,
                   "label": "Additional filter differential pressure (AFDP, mbar)"},
     "primary": "AFDP", "sign": +1, "implied": [],
     "subsystems": ["intake", "compressor", "generator_output"],
     "notes": ["The baseline model gives the expected TEY sensitivity to AFDP (model-derived, ceteris paribus).",
               "No implied deltas: historically AFDP rises WITH load (more airflow), so the AFDP->TEY slope "
               "would wrongly suggest more output from a dirtier filter. Filter fouling at constant airflow is "
               "not separable in this data."]},
    {"intent_id": "reduce_cooling_water", "label": "Reduce cooling-water flow",
     "description": "Less cooling-water flow (e.g. condenser / auxiliary cooling).",
     "magnitude": {"unit": "%", "default": 10.0, "min": 1.0, "max": 50.0, "step": 1.0,
                   "label": "Flow reduction (%) — qualitative only, not modelled"},
     "primary": None, "sign": 0, "implied": [], "observable": False,
     "subsystems": ["generator_output"],
     "notes": ["not observable in this data; qualitative only: the UCI gas-turbine dataset has no cooling-water "
               "measurement, so no delta, sensitivity or slope can be computed."]},
    {"intent_id": "custom", "label": "Custom change (free text + explicit deltas)",
     "description": "Describe the change in words and give explicit measurement deltas (published units).",
     "magnitude": None, "primary": None, "sign": 0, "implied": [], "subsystems": [],
     "notes": ["Only the deltas you enter are modelled; nothing is implied from them."]},
]
_BY_ID = {i["intent_id"]: i for i in INTENTS}
MEAS_SUBSYSTEM = {"AFDP": "intake", "AT": "intake", "AH": "intake", "AP": "intake", "CDP": "compressor",
                  "TIT": "combustion_turbine", "TAT": "combustion_turbine", "TEY": "generator_output",
                  "GTEP": "exhaust_emissions", "CO": "exhaust_emissions", "NOX": "exhaust_emissions"}


def list_intents() -> list[IntentInfo]:
    return [IntentInfo(intent_id=i["intent_id"], label=i["label"], description=i["description"],
                       magnitude=MagnitudeSpec(**i["magnitude"]) if i.get("magnitude") else None,
                       subsystems=i["subsystems"], primary_measurement=i.get("primary"),
                       observable=i.get("observable", True), notes=i["notes"]) for i in INTENTS]


def get_intent(intent_id: str) -> dict[str, Any]:
    if intent_id not in _BY_ID:
        raise KeyError(f"unknown intent '{intent_id}' (expected one of {', '.join(_BY_ID)})")
    return _BY_ID[intent_id]


def _r(x: float, nd: int = 4) -> Optional[float]:
    return round(float(x), nd) if x is not None and math.isfinite(float(x)) else None


def slope(stats: dict[str, Any], y: str, x: str) -> tuple[Optional[float], Optional[float]]:
    """Least-squares slope of y on x (cov/var) and Pearson r over the training years."""
    try:
        var = stats["cov"][x][x]
        return (stats["cov"][x][y] / var if var > 0 else None), stats["corr"][x][y]
    except KeyError:
        return None, None


def _check_magnitude(spec: dict[str, Any], magnitude: Any) -> float:
    if magnitude is None:
        return float(spec["default"])
    if isinstance(magnitude, bool):
        raise ValueError("magnitude must be a number")
    m = float(magnitude)
    if not math.isfinite(m):
        raise ValueError("magnitude must be finite")
    if not spec["min"] <= m <= spec["max"]:
        raise ValueError(f"magnitude must be within [{spec['min']:g}, {spec['max']:g}] {spec['unit']}")
    return m


def build_change(intent_id: Optional[str], magnitude: Any = None, custom: Optional[CustomIntent] = None,
                 stats: Optional[dict[str, Any]] = None, dataset_id: str = DEFAULT_DATASET) -> ModelledChange:
    """Intent -> ModelledChange. ``stats`` defaults to sensitivity.training_stats(dataset_id). ValueError -> 422."""
    if not intent_id:
        intent_id = "custom" if custom is not None else None
    if not intent_id:
        raise ValueError("intent_id or custom is required")
    spec = get_intent(intent_id)
    if stats is None:
        from app.plant.sensitivity import training_stats

        stats = training_stats(dataset_id)
    years = list(stats.get("years") or [])

    if intent_id == "custom":
        if custom is None:
            raise ValueError("custom intent needs custom={text, deltas}")
        bad = [k for k in custom.deltas if k not in MEASUREMENT_KEYS]
        if bad:
            raise ValueError(f"unknown measurement(s) {bad}; expected {MEASUREMENT_KEYS}")
        deltas = []
        for k, v in custom.deltas.items():
            if not math.isfinite(float(v)):
                raise ValueError(f"delta for {k} must be finite")
            if float(v) == 0.0:
                continue
            deltas.append(MeasurementDelta(measurement=k, delta=float(v), unit=MEASUREMENTS[k]["unit"],
                                           role="primary", basis="explicit operator-entered delta",
                                           provenance="operator_intent"))
        subs = sorted({MEAS_SUBSYSTEM[d.measurement] for d in deltas})
        return ModelledChange(intent_id="custom", label="Custom change", text=custom.text.strip()[:500],
                              deltas=deltas, subsystems=subs, observable=bool(deltas),
                              qualitative_notes=([] if deltas else
                                                 ["No measurement deltas given: qualitative only, nothing modelled."])
                              + spec["notes"], training_years=years)

    mspec = spec["magnitude"]
    mag = _check_magnitude(mspec, magnitude)
    text = spec["label"].replace("X", f"{mag:g}")
    if not spec.get("observable", True) or spec["primary"] is None:
        return ModelledChange(intent_id=intent_id, label=spec["label"], text=text, magnitude=mag, unit=mspec["unit"],
                              deltas=[], subsystems=spec["subsystems"], observable=False,
                              qualitative_notes=list(spec["notes"]), training_years=years)

    primary = spec["primary"]
    d0 = spec["sign"] * mag
    deltas = [MeasurementDelta(measurement=primary, delta=_r(d0), unit=MEASUREMENTS[primary]["unit"], role="primary",
                               basis=f"operator intent: {text}", provenance="operator_intent")]
    for m in spec["implied"]:
        s, r = slope(stats, m, primary)
        if s is None:
            continue
        deltas.append(MeasurementDelta(
            measurement=m, delta=_r(s * d0), unit=MEASUREMENTS[m]["unit"], role="implied",
            basis=(f"d{m}/d{primary} = {s:+.4g} {MEASUREMENTS[m]['unit']} per {MEASUREMENTS[primary]['unit']} "
                   f"(r={r:+.2f}, least-squares over {years}) x {d0:+g}"),
            provenance="statistical_association", slope=_r(s, 6), pearson_r=_r(r, 3), slope_of=primary))
    return ModelledChange(intent_id=intent_id, label=spec["label"], text=text, magnitude=mag, unit=mspec["unit"],
                          deltas=deltas, subsystems=spec["subsystems"], observable=True,
                          qualitative_notes=list(spec["notes"]), slope_label=SLOPE_LABEL, training_years=years)
