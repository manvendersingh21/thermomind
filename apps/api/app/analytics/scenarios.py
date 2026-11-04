"""Scenario registry and overlay application.

Every scenario except S01_NORMAL is a SYNTHETIC overlay applied to a COPY of real
UCI rows. Original rows are never mutated. The ``expected_behavior`` text in each
``ScenarioInfo`` is for documentation/UI only: it describes what a good
investigator should conclude and MUST NEVER be passed to the agent (it would
leak the answer).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.schemas import MEASUREMENT_KEYS, ScenarioInfo, Transformation

DEFAULT_YEAR = 2014
DEFAULT_START = 1200
DEFAULT_END = 1320
DEFAULT_SEED = 42

SCENARIOS: dict[str, ScenarioInfo] = {
    "S01_NORMAL": ScenarioInfo(
        scenario_id="S01_NORMAL",
        title="Normal operation (real data only)",
        synthetic=False,
        description="Real UCI rows for the window with no overlay. Used as the control case.",
        rationale="A control case lets us check that the pipeline does not invent faults on unmodified real data.",
        affected_measurements=[],
        expected_behavior=(
            "No notable deviation; the top hypothesis should be 'unknown'/no fault with low support, and the "
            "report should be informational. Any residual drift reflects real dispatch/ambient variation."
        ),
    ),
    "S02_INTAKE_RESTRICTION": ScenarioInfo(
        scenario_id="S02_INTAKE_RESTRICTION",
        title="Progressive intake filter restriction (synthetic)",
        synthetic=True,
        description=(
            "AFDP ramps up linearly by +1.8 mbar across the window (plus small seeded noise, sd 0.05), TEY is "
            "scaled down linearly to 0.965x (up to -3.5%), and CDP is scaled down linearly to 0.99x."
        ),
        rationale=(
            "Progressive intake filter fouling increases the filter differential pressure and reduces compressor "
            "mass flow, lowering compressor discharge pressure and output. This is a documented physical tendency "
            "used here as a synthetic illustration; it is not a recorded event at the source plant."
        ),
        affected_measurements=["AFDP", "TEY", "CDP"],
        expected_behavior=(
            "AFDP window-vs-reference deviation and positive trend slope are notable; the TEY residual against the "
            "baseline is negative and notable; CDP drifts slightly low. The coherent multi-sensor pattern should "
            "rank 'intake_restriction' first, while noting the data is synthetic and no fault label exists."
        ),
    ),
    "S03_SENSOR_INCONSISTENCY": ScenarioInfo(
        scenario_id="S03_SENSOR_INCONSISTENCY",
        title="Isolated CDP sensor inconsistency (synthetic)",
        synthetic=True,
        description=(
            "CDP alone receives a +1.5 mbar offset (plus small seeded noise) for window rows [40, 80). TEY, AFDP, "
            "TIT, GTEP and all other measurements are untouched."
        ),
        rationale=(
            "A step in one pressure reading with no corresponding change in flow, temperature or output has no "
            "coherent mechanical explanation; the most parsimonious reading is a sensor/instrumentation issue."
        ),
        affected_measurements=["CDP"],
        expected_behavior=(
            "CDP shows a notable step/segment while AFDP, TEY residual, TIT and GTEP stay within normal bounds. "
            "'sensor_issue' should rank first; 'intake_restriction' should be contradicted by the flat AFDP."
        ),
    ),
    "S04_AMBIENT_SHIFT": ScenarioInfo(
        scenario_id="S04_AMBIENT_SHIFT",
        title="Ambient condition shift (synthetic)",
        synthetic=True,
        description=(
            "AT ramps up by +6 degC across the window and AH ramps down by 10 percentage points; TEY and all "
            "turbine-internal readings are left as recorded."
        ),
        rationale=(
            "Ambient temperature and humidity change the air density and therefore the achievable output; such "
            "shifts are operating-condition effects, not equipment faults. Because TEY is left as recorded the "
            "baseline model will see ambient inputs that no longer match the output."
        ),
        affected_measurements=["AT", "AH"],
        expected_behavior=(
            "Ambient evidence (AT, AH) is notable while AFDP is flat; the case should be read as an "
            "operating-condition change (or an inconsistent ambient overlay) rather than an intake fault."
        ),
    ),
}


@dataclass
class ScenarioResult:
    scenario_id: str
    synthetic: bool
    seed: int
    frame: pd.DataFrame
    transformations: list[Transformation] = field(default_factory=list)
    affected_measurements: list[str] = field(default_factory=list)


def _ramp(n: int, start: float, end: float) -> np.ndarray:
    if n <= 1:
        return np.full(n, end, dtype=float)
    return np.linspace(start, end, n)


def _add_ramp(frame: pd.DataFrame, col: str, delta_end: float, noise_sd: float, rng: np.random.Generator,
              unit: str) -> Transformation:
    n = len(frame)
    noise = rng.normal(0.0, noise_sd, n) if noise_sd > 0 else np.zeros(n)
    frame[col] = frame[col].to_numpy(dtype=float) + _ramp(n, 0.0, delta_end) + noise
    return Transformation(
        measurement=col, operation="add_ramp",
        params={"start_delta": 0.0, "end_delta": delta_end, "noise_sd": noise_sd, "rows": [0, n], "unit": unit},
        description=f"{col}: add linear ramp from +0 to +{delta_end} {unit} over window rows [0, {n}) "
                    f"plus N(0, {noise_sd}) seeded noise",
    )


def _multiply_ramp(frame: pd.DataFrame, col: str, factor_end: float) -> Transformation:
    n = len(frame)
    frame[col] = frame[col].to_numpy(dtype=float) * _ramp(n, 1.0, factor_end)
    return Transformation(
        measurement=col, operation="multiply_ramp",
        params={"start_factor": 1.0, "end_factor": factor_end, "rows": [0, n]},
        description=f"{col}: multiply by linear ramp from 1.0 to {factor_end} over window rows [0, {n}) "
                    f"(up to {100 * (factor_end - 1):+.1f}%)",
    )


def _add_offset(frame: pd.DataFrame, col: str, offset: float, rows: tuple[int, int], noise_sd: float,
                rng: np.random.Generator, unit: str) -> Transformation:
    n = len(frame)
    lo, hi = max(0, rows[0]), min(n, rows[1])
    vals = frame[col].to_numpy(dtype=float).copy()
    k = max(0, hi - lo)
    noise = rng.normal(0.0, noise_sd, k) if noise_sd > 0 and k else np.zeros(k)
    vals[lo:hi] = vals[lo:hi] + offset + noise
    frame[col] = vals
    return Transformation(
        measurement=col, operation="add_offset",
        params={"offset": offset, "noise_sd": noise_sd, "rows": [lo, hi], "unit": unit},
        description=f"{col}: add constant offset {offset:+} {unit} to window rows [{lo}, {hi}) "
                    f"plus N(0, {noise_sd}) seeded noise",
    )


def apply_scenario(window: pd.DataFrame, scenario_id: str, seed: int | None = None) -> ScenarioResult:
    """Return a COPY of ``window`` with the scenario overlay applied. Never mutates the input."""
    if scenario_id not in SCENARIOS:
        raise KeyError(f"unknown scenario_id: {scenario_id}")
    info = SCENARIOS[scenario_id]
    seed = int(info.default_seed if seed is None else seed)
    rng = np.random.default_rng(seed)
    frame = window.copy(deep=True)
    transformations: list[Transformation] = []

    if scenario_id == "S01_NORMAL":
        pass
    elif scenario_id == "S02_INTAKE_RESTRICTION":
        transformations.append(_add_ramp(frame, "AFDP", 1.8, 0.05, rng, "mbar"))
        transformations.append(_multiply_ramp(frame, "TEY", 0.965))
        transformations.append(_multiply_ramp(frame, "CDP", 0.99))
    elif scenario_id == "S03_SENSOR_INCONSISTENCY":
        transformations.append(_add_offset(frame, "CDP", 1.5, (40, 80), 0.05, rng, "mbar"))
    elif scenario_id == "S04_AMBIENT_SHIFT":
        transformations.append(_add_ramp(frame, "AT", 6.0, 0.1, rng, "degC"))
        transformations.append(_add_ramp(frame, "AH", -10.0, 0.2, rng, "%"))
    else:  # pragma: no cover - registry and dispatcher kept in sync
        raise KeyError(f"scenario {scenario_id} has no transform implementation")

    for col in MEASUREMENT_KEYS:
        if col in frame.columns:
            frame[col] = frame[col].astype("float64")

    return ScenarioResult(
        scenario_id=scenario_id,
        synthetic=bool(info.synthetic),
        seed=seed,
        frame=frame,
        transformations=transformations,
        affected_measurements=list(info.affected_measurements),
    )
