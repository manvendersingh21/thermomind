"""Tests for app.analytics.scenarios (ML agent)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analytics.scenarios import SCENARIOS, apply_scenario
from app.schemas import MEASUREMENT_KEYS, ScenarioInfo
from tests.test_baseline import raw_frame, year_2014  # noqa: F401  (session fixtures)

EXPECTED_IDS = ["S01_NORMAL", "S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT"]


@pytest.fixture
def window(year_2014):  # noqa: F811
    return year_2014.iloc[1200:1320].reset_index(drop=True)


def test_registry_contract():
    assert list(SCENARIOS) == EXPECTED_IDS
    for sid, info in SCENARIOS.items():
        assert isinstance(info, ScenarioInfo) and info.scenario_id == sid
        assert (info.default_year, info.default_start, info.default_end, info.default_seed) == (2014, 1200, 1320, 42)
        assert info.expected_behavior and info.rationale
    assert SCENARIOS["S01_NORMAL"].synthetic is False and SCENARIOS["S01_NORMAL"].affected_measurements == []
    assert SCENARIOS["S02_INTAKE_RESTRICTION"].affected_measurements == ["AFDP", "TEY", "CDP"]
    assert SCENARIOS["S03_SENSOR_INCONSISTENCY"].affected_measurements == ["CDP"]
    assert SCENARIOS["S04_AMBIENT_SHIFT"].affected_measurements == ["AT", "AH"]


def test_unknown_scenario_raises(window):
    with pytest.raises(KeyError):
        apply_scenario(window, "S99_NOPE")


def test_s01_overlay_equals_original(window):
    res = apply_scenario(window, "S01_NORMAL")
    assert res.synthetic is False and res.transformations == [] and res.affected_measurements == []
    pd.testing.assert_frame_equal(res.frame, window)
    assert res.frame is not window


def test_s02_does_not_mutate_input_and_returns_copy(window):
    before = window.copy(deep=True)
    res = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=42)
    pd.testing.assert_frame_equal(window, before)
    assert res.frame is not window
    assert list(res.frame.columns) == list(window.columns)
    assert len(res.frame) == len(window)
    # overlay actually changed the affected columns and nothing else
    for col in MEASUREMENT_KEYS:
        if col in ("AFDP", "TEY", "CDP"):
            assert not np.allclose(res.frame[col], window[col])
        else:
            np.testing.assert_array_equal(res.frame[col].to_numpy(), window[col].to_numpy())
    np.testing.assert_array_equal(res.frame["row_index"].to_numpy(), window["row_index"].to_numpy())


def test_s02_transform_params_and_magnitudes(window):
    res = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=42)
    ops = {(t.measurement, t.operation): t for t in res.transformations}
    assert set(ops) == {("AFDP", "add_ramp"), ("TEY", "multiply_ramp"), ("CDP", "multiply_ramp")}
    assert ops[("AFDP", "add_ramp")].params["end_delta"] == 1.8 and ops[("AFDP", "add_ramp")].params["noise_sd"] == 0.05
    assert ops[("TEY", "multiply_ramp")].params["end_factor"] == 0.965
    assert ops[("CDP", "multiply_ramp")].params["end_factor"] == 0.99
    assert all(t.params["rows"] == [0, 120] for t in res.transformations)
    assert all(t.description for t in res.transformations)
    # TEY ratio ramps linearly from 1.0 to 0.965 (exact: no noise on the multiply ramp)
    ratio = (res.frame["TEY"] / window["TEY"]).to_numpy()
    assert abs(ratio[0] - 1.0) < 1e-9 and abs(ratio[-1] - 0.965) < 1e-9
    # AFDP delta ends near +1.8 (noise sd 0.05)
    d_afdp = (res.frame["AFDP"] - window["AFDP"]).to_numpy()
    assert abs(d_afdp[0]) < 0.3 and abs(d_afdp[-1] - 1.8) < 0.3
    assert res.synthetic is True and res.seed == 42


def test_synthetic_flags_propagate(window):
    for sid, info in SCENARIOS.items():
        res = apply_scenario(window, sid)
        assert res.synthetic == info.synthetic
        assert res.affected_measurements == info.affected_measurements
        assert {t.measurement for t in res.transformations} == set(info.affected_measurements)


def test_s03_only_touches_cdp_in_subrange(window):
    before = window.copy(deep=True)
    res = apply_scenario(window, "S03_SENSOR_INCONSISTENCY", seed=42)
    pd.testing.assert_frame_equal(window, before)
    for col in MEASUREMENT_KEYS:
        if col != "CDP":
            np.testing.assert_array_equal(res.frame[col].to_numpy(), window[col].to_numpy())
    diff = (res.frame["CDP"] - window["CDP"]).to_numpy()
    assert np.all(diff[:40] == 0) and np.all(diff[80:] == 0)
    assert np.all(np.abs(diff[40:80] - 1.5) < 0.3)
    [t] = res.transformations
    assert t.measurement == "CDP" and t.operation == "add_offset"
    assert t.params["offset"] == 1.5 and t.params["rows"] == [40, 80]


def test_s04_touches_only_ambient(window):
    res = apply_scenario(window, "S04_AMBIENT_SHIFT", seed=42)
    for col in MEASUREMENT_KEYS:
        if col not in ("AT", "AH"):
            np.testing.assert_array_equal(res.frame[col].to_numpy(), window[col].to_numpy())
    d_at = (res.frame["AT"] - window["AT"]).to_numpy()
    d_ah = (res.frame["AH"] - window["AH"]).to_numpy()
    assert abs(d_at[-1] - 6.0) < 0.5 and abs(d_ah[-1] + 10.0) < 1.0


def test_seed_determinism(window):
    a = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=7)
    b = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=7)
    c = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=8)
    pd.testing.assert_frame_equal(a.frame, b.frame)
    assert not np.allclose(a.frame["AFDP"], c.frame["AFDP"])
    assert apply_scenario(window, "S02_INTAKE_RESTRICTION").seed == 42
