"""Scenario endpoints: registry list and preview (original vs synthetic overlay)."""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from app import config, services
from app.schemas import (
    MEASUREMENT_KEYS,
    MEASUREMENTS,
    TARGET_KEY,
    ScenarioInfo,
    ScenarioPreviewRequest,
    ScenarioPreviewResponse,
    ScenarioSeries,
    SeriesPoint,
)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
log = logging.getLogger("thermomind.api.scenarios")


def _points(frame: pd.DataFrame, col: str) -> list[SeriesPoint]:
    idx = frame["row_index"].to_numpy()
    vals = frame[col].to_numpy(dtype="float64")
    return [
        SeriesPoint(row_index=int(i), value=(float(v) if np.isfinite(v) else None))
        for i, v in zip(idx, vals)
    ]


def _expected_points(frame: pd.DataFrame, preds: np.ndarray) -> list[SeriesPoint]:
    idx = frame["row_index"].to_numpy()
    return [
        SeriesPoint(row_index=int(i), value=None, expected=(float(p) if math.isfinite(float(p)) else None))
        for i, p in zip(idx, preds)
    ]


@router.get("", response_model=list[ScenarioInfo])
def list_scenarios() -> list[ScenarioInfo]:
    return list(services.get_scenarios().values())


@router.post("/preview", response_model=ScenarioPreviewResponse)
def preview_scenario(req: ScenarioPreviewRequest) -> ScenarioPreviewResponse:
    from app.analytics.scenarios import apply_scenario

    scenario = services.get_scenario(req.scenario_id)  # KeyError -> 404
    services.validate_window(req.start_index, req.end_index)  # ValueError -> 422
    measurements = [m.strip().upper() for m in (req.measurements or ["AFDP", "TEY", "CDP"])]
    bad = [m for m in measurements if m not in MEASUREMENT_KEYS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown measurement(s): {', '.join(bad)}")

    bundle = services.get_repo().get(req.dataset_id)  # KeyError -> 404
    window = bundle.window(req.year, req.start_index, req.end_index)  # IndexError -> 422
    original = window.copy(deep=True)
    seed = scenario.default_seed if req.seed is None else int(req.seed)
    result = apply_scenario(window, req.scenario_id, seed)

    warnings: list[str] = []
    ref_start, ref_end = services.reference_bounds(req.start_index)
    if ref_end - ref_start < config.DEFAULT_REFERENCE_ROWS:
        warnings.append(
            f"only {ref_end - ref_start} reference rows precede this window (investigations use up to "
            f"{config.DEFAULT_REFERENCE_ROWS}); an investigation needs at least {services.MIN_REFERENCE_ROWS}."
        )

    model = services.get_model()
    expected_preds: np.ndarray | None = None
    if model is not None:
        try:
            expected_preds = model.predict(result.frame)
        except Exception as exc:  # noqa: BLE001 - preview must still work without the model
            log.warning("expected TEY unavailable for preview: %s", type(exc).__name__)
            warnings.append("model-derived expected TEY unavailable for this window")

    series: list[ScenarioSeries] = []
    for m in measurements:
        expected = None
        if m == TARGET_KEY and expected_preds is not None:
            expected = _expected_points(result.frame, expected_preds)
        series.append(
            ScenarioSeries(
                measure=m,
                unit=MEASUREMENTS[m]["unit"],
                original=_points(original, m),
                overlay=_points(result.frame, m),
                expected=expected,
            )
        )

    provenance = {
        "source": bundle.source,
        "dataset_id": bundle.dataset_id,
        "original": "real_observation (unmodified rows from the dataset)",
        "overlay": "synthetic_overlay applied to a copy" if result.synthetic else "identical to original (no overlay)",
        "expected": (
            f"model_derived expected TEY from {model.version} given the overlay features"
            if model is not None else "model not available"
        ),
        "affected_measurements": list(result.affected_measurements),
        "time_axis_type": "ordered_hourly_sample_without_actual_timestamp",
        "has_timestamps": False,
        "reference_rows_available": ref_end - ref_start,
        "warnings": warnings,
    }
    return ScenarioPreviewResponse(
        dataset_id=req.dataset_id,
        scenario_id=req.scenario_id,
        synthetic=bool(result.synthetic),
        scenario_label=services.scenario_label_for(scenario),
        year=req.year,
        start_index=req.start_index,
        end_index=req.end_index,
        seed=int(result.seed),
        transformations=list(result.transformations),
        series=series,
        provenance=provenance,
    )
