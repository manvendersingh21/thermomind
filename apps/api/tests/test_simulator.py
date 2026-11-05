"""Tests for the SIMULATED gas-turbine plant (app.simulator). Software model only."""
from __future__ import annotations

import json
import math
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, services
from app.schemas import MEASUREMENT_KEYS
from app.simulator import calibration as cal
from app.simulator.engine import SimEngine, get_engine

pytestmark = pytest.mark.skipif(
    not (cal.raw_dir() / "gt_2014.csv").exists(), reason="UCI raw files not available"
)


def _engine(start_index: int = 100, rows_per_hour: int = 60) -> SimEngine:
    e = SimEngine()
    e.configure(year=2014, start_index=start_index, rows_per_hour=rows_per_hour)
    return e


def test_steady_state_within_uci_ranges():
    e = _engine()
    recs = e.run_steps(90)
    real = cal.year_frame(2014)
    last = recs[-1]["channels"]
    for ch in ("AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP"):
        lo, hi = real[ch].min(), real[ch].max()
        span = hi - lo
        assert lo - 0.1 * span <= last[ch] <= hi + 0.1 * span, (ch, last[ch], lo, hi)
    assert abs(recs[-1]["omega_pu"] - 1.0) < 0.01
    assert set(last) == set(MEASUREMENT_KEYS)


def test_hot_day_lowers_base_load_output():
    base = _engine().run_steps(120, setpoint_override=400.0)[-1]
    e = _engine()
    e.add_fault("hot_day", 15.0)
    hot = e.run_steps(120, setpoint_override=400.0)[-1]
    assert base["dispatch_clipped"] and hot["dispatch_clipped"]
    assert hot["channels"]["TEY"] < base["channels"]["TEY"] - 3.0
    assert hot["synthetic"] is True and hot["provenance"]["AT"] == "synthetic_fault"


def test_intake_fouling_raises_afdp_and_lowers_tey():
    e = _engine(rows_per_hour=1)  # one real row per simulated hour: ambient constant during the test
    before = e.run_steps(60, setpoint_override=400.0)[-1]
    e.add_fault("intake_fouling", 60.0)  # fouling factor +60 per simulated hour
    after = e.run_steps(240, setpoint_override=400.0)[-1]
    assert after["channels"]["AFDP"] > before["channels"]["AFDP"] * 1.5
    assert after["channels"]["TEY"] < before["channels"]["TEY"] - 0.5
    assert after["provenance"]["AFDP"] == "synthetic_fault"
    assert before["synthetic"] is False


def test_governor_follows_setpoint_step():
    e = _engine()
    e.run_steps(120, setpoint_override=120.0)
    recs = e.run_steps(180, setpoint_override=140.0)
    last = recs[-1]
    assert abs(last["channels"]["TEY"] - 140.0) < 0.5
    assert abs(last["omega_pu"] - 1.0) < 1e-3
    assert max(abs(r["omega_pu"] - 1.0) for r in recs) < 0.05
    assert "simulated plant's own control" in last["control"]


def test_energy_closure_below_two_percent():
    e = _engine()
    recs = e.run_steps(60, setpoint_override=110.0) + e.run_steps(120, setpoint_override=150.0)
    worst = max(r["energy_closure_pct"] for r in recs)
    assert math.isfinite(worst) and worst < 2.0


def test_no_timestamps_and_provenance_fields():
    rec = _engine().run_steps(3)[-1]
    flat = json.dumps(rec).lower()
    assert "timestamp" not in flat and "date" not in flat
    assert rec["source_year"] == 2014 and isinstance(rec["row_index"], int)
    assert {rec["provenance"][k] for k in ("AT", "AP", "AH")} == {"real_input"}
    assert {rec["provenance"][k] for k in MEASUREMENT_KEYS if k not in ("AT", "AP", "AH")} == {"simulated"}
    assert "energy_closure_pct" in rec


def test_sensor_faults_labelled_and_stuck_holds():
    e = _engine()
    e.run_steps(5)
    f = e.add_fault("sensor_stuck", 0.0, channel="TAT")
    recs = e.run_steps(30, setpoint_override=150.0)
    assert len({r["channels"]["TAT"] for r in recs}) == 1
    assert all(r["provenance"]["TAT"] == "synthetic_fault" and r["synthetic"] for r in recs)
    assert f["synthetic"] is True
    assert e.remove_fault(f["id"])


def test_calibration_report_real_numbers():
    _, rep = cal.get_calibration()
    assert rep["status"] == "calibrated" and rep["test_year"] == 2014 and rep["fit_rows"] == 200
    for ch in ("TIT", "TAT", "CDP", "AFDP", "GTEP", "NOX", "CO"):
        assert math.isfinite(rep["per_channel_mae_test"][ch])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "sim_test.db")
    services.reset()
    app = FastAPI()
    from app.simulator import router as r

    app.include_router(r, prefix="/api")
    eng = get_engine()
    eng.action("reset")
    with TestClient(app) as c:
        yield c
    eng.action("reset")
    services.reset()


def test_endpoints_and_register_window(client):
    assert client.post("/api/simulator/run", json={"action": "fly"}).status_code == 422
    assert client.post("/api/simulator/run", json={"action": "start", "year": 1999}).status_code == 422
    assert client.post("/api/simulator/faults", json={"kind": "sensor_bias", "magnitude": 1.0}).status_code == 422
    assert client.post("/api/simulator/faults", json={"kind": "melt", "magnitude": 1.0}).status_code == 422
    r = client.post("/api/simulator/run", json={"action": "start", "year": 2014, "start_index": 300, "speed": 1000})
    assert r.status_code == 200 and r.json()["status"] == "running"
    deadline = time.time() + 20
    while client.get("/api/simulator/state").json()["buffer_len"] < 60 and time.time() < deadline:
        time.sleep(0.1)
    fr = client.post("/api/simulator/faults", json={"kind": "sensor_bias", "magnitude": 2.0, "channel": "AFDP"})
    assert fr.status_code == 200 and fr.json()["synthetic"] is True
    assert client.post("/api/simulator/run", json={"action": "pause"}).json()["status"] == "paused"
    st = client.get("/api/simulator/state").json()
    assert st["simulated"] is True and st["buffer_len"] >= 60
    assert client.delete(f"/api/simulator/faults/{fr.json()['id']}").status_code == 200
    assert client.delete("/api/simulator/faults/nope").status_code == 404
    h = client.get("/api/simulator/history", params={"n": 50}).json()
    assert h["n"] == 50 and len(h["records"][0]["channels"]) == 11
    assert client.get("/api/simulator/history", params={"n": 0}).status_code == 422
    with client.stream("GET", "/api/simulator/stream", params={"max_events": 1}) as s:
        body = "".join(s.iter_text())
    assert body.startswith("data: ") and '"simulated": true' in body
    assert client.post("/api/simulator/register-window", json={"last_n": 5}).status_code == 422
    reg = client.post("/api/simulator/register-window", json={"last_n": 48})
    assert reg.status_code == 200, reg.text
    d = reg.json()
    assert d["dataset_id"].startswith("ds_sim_") and d["source"] == "SIMULATED_PLANT"
    assert d["warnings"] == ["simulated physics model; synthetic faults may be present"]
    bundle = services.get_repo().get(d["dataset_id"])
    summ = bundle.summary()
    assert summ.has_timestamps is False and summ.source == "SIMULATED_PLANT" and summ.row_count == 48
    assert len(bundle.window(2014, 24, 48)) == 24
    assert client.get("/api/simulator/calibration").json()["status"] == "calibrated"
