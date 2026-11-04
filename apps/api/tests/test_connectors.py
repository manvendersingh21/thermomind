"""Plant connector adapters: simulated, read-only, no control path, no fabricated timestamps."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.connectors import base
from app.connectors import router as router_mod
from app.connectors.simulated_cmms import SimulatedCmms
from app.connectors.simulated_historian import TIME_AXIS, HistorianError, SimulatedHistorian
from app.connectors.simulated_notifier import SimulatedNotifier
from app.data.uci_loader import MEASUREMENT_COLUMNS, load_csv_files

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "gt_2014_sample300.csv"
FORBIDDEN_KEYS = ("time", "date", "stamp", "utc")


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(scope="module")
def bundle():
    return load_csv_files([("gt_2014.csv", FIXTURE.read_bytes())])


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def hist(bundle, clock):
    return SimulatedHistorian(lambda y: bundle.year_frame(y), clock=clock)


@pytest.fixture()
def client(bundle, clock):
    h = SimulatedHistorian(lambda y: bundle.year_frame(y), clock=clock)
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api")
    app.dependency_overrides[router_mod.get_historian] = lambda: h
    cmms, notifier = SimulatedCmms(), SimulatedNotifier()
    app.dependency_overrides[router_mod.get_cmms] = lambda: cmms
    app.dependency_overrides[router_mod.get_notifier] = lambda: notifier
    return TestClient(app)


def test_interfaces_are_abstract_and_implemented():
    for cls in (base.HistorianSource, base.CmmsSink, base.Notifier):
        assert inspect.isabstract(cls)
    assert issubclass(SimulatedHistorian, base.HistorianSource)
    assert issubclass(SimulatedCmms, base.CmmsSink)
    assert issubclass(SimulatedNotifier, base.Notifier)
    assert {"describe", "tags", "read_window", "latest"} <= set(base.HistorianSource.__abstractmethods__)


def test_control_system_has_no_write_methods():
    public = [n for n, _ in inspect.getmembers(base.ControlSystem, inspect.isfunction) if not n.startswith("_")]
    assert public == ["capabilities"]
    caps = base.ControlSystem().capabilities()
    assert caps["read"] is False and caps["write"] is False
    assert "Read-only decision support by design" in caps["note"]
    for cls in (base.HistorianSource, SimulatedHistorian, base.CmmsSink, SimulatedCmms):
        names = {n for n in dir(cls) if not n.startswith("_")}
        assert not {n for n in names if n.startswith(("write", "set_", "send_command", "submit"))}


def test_cmms_draft_only_never_submitted():
    c = SimulatedCmms()
    out = c.draft_work_order({"title": "Inspect air filter"})
    assert out["status"] == "DRAFT_NOT_SUBMITTED" and out["id"]
    assert not hasattr(c, "submit")
    drafts = c.drafts()
    assert len(drafts) == 1 and drafts[0]["simulated"] is True and drafts[0]["status"] == "DRAFT_NOT_SUBMITTED"


def test_notifier_is_simulated_in_app():
    n = SimulatedNotifier()
    out = n.notify("operator", "hello")
    assert out["delivery"] == "in_app_simulated"
    assert any(i["id"] == out["id"] and i["simulated"] for i in n.outbox())


def test_replay_order_manual_ticks(hist):
    hist.start(2014, advance_rate=0, start_index=10)
    hist.tick()
    hist.tick()
    rows = hist.latest(10)["rows"]
    assert [r["row_index"] for r in rows] == [10, 11, 12]
    assert [r["replay_tick"] for r in rows] == [0, 1, 2]
    assert all(r["source_year"] == 2014 for r in rows)
    assert set(MEASUREMENT_COLUMNS) <= set(rows[0])
    assert hist.cursor()["replay_tick"] == 2


def test_replay_matches_real_rows(hist, bundle):
    hist.start(2014, advance_rate=0, start_index=5)
    hist.tick(3)
    real = bundle.year_frame(2014)
    for r in hist.latest(10)["rows"]:
        assert r["TEY"] == pytest.approx(float(real.loc[r["row_index"], "TEY"]))


def test_rate_advance_and_stop_freezes_cursor(hist, clock):
    hist.start(2014, advance_rate=2.0, start_index=0)
    clock.t = 3.0  # 6 rows due
    assert hist.status()["row_index"] == 6
    hist.stop()
    clock.t = 100.0
    c = hist.status()
    assert c["running"] is False and c["row_index"] == 6 and c["replay_tick"] == 6
    clock.t = 101.0
    assert hist.latest(1)["rows"][0]["row_index"] == 6  # stays put


def test_cursor_monotonic_and_stops_at_end(hist, clock):
    hist.start(2014, advance_rate=1000, start_index=0)
    seen = []
    for i in range(1, 6):
        clock.t = i * 0.1
        seen.append(hist.status()["row_index"])
    assert seen == sorted(seen)
    clock.t = 10_000.0
    c = hist.status()
    assert c["finished"] is True and c["running"] is False
    assert c["row_index"] == c["rows_in_year"] - 1


def test_rows_carry_no_timestamps(hist):
    hist.start(2014, advance_rate=0, start_index=0)
    hist.tick(5)
    payload = hist.latest(10)
    assert payload["simulated"] is True and payload["time_axis"] == TIME_AXIS
    for row in payload["rows"]:
        assert not [k for k in row if any(f in k.lower() for f in FORBIDDEN_KEYS)]
    # "time_axis" is the explicit no-timestamp label, not a timestamp
    assert not [k for k in payload["cursor"] if k != "time_axis" and any(f in k.lower() for f in FORBIDDEN_KEYS)]


def test_invalid_inputs(hist):
    with pytest.raises(HistorianError):
        hist.start(2014, start_index=10_000)
    with pytest.raises(HistorianError):
        hist.start(2014, advance_rate=-1)
    with pytest.raises(HistorianError):
        hist.start(1999)
    with pytest.raises(HistorianError):
        hist.tick()  # not started
    with pytest.raises(HistorianError):
        hist.read_window("NOPE", 2014, 0, 5)


def test_read_window_and_tags(hist):
    w = hist.read_window("TEY", 2014, 0, 4)
    assert [p["row_index"] for p in w] == [0, 1, 2, 3]
    tags = hist.tags()
    assert [t["tag"] for t in tags] == list(MEASUREMENT_COLUMNS)


def test_status_endpoint_shape(client):
    body = client.get("/api/connectors/status").json()
    assert body["simulated"] is True and body["read_only"] is True
    by_kind = {c["kind"]: c for c in body["connectors"]}
    assert set(by_kind) == {"historian", "cmms", "notifier", "control_system"}
    for c in body["connectors"]:
        assert {"name", "kind", "mode", "description", "real_adapter_needs"} <= set(c)
    assert by_kind["historian"]["mode"] == "simulated"
    ctl = by_kind["control_system"]
    assert ctl["mode"] == "not_connected" and ctl["detail"]["write"] is False and ctl["detail"]["read"] is False


def test_historian_endpoints(client):
    r = client.post("/api/connectors/historian/start", json={"year": 2014, "advance_rate": 0, "start_index": 20})
    assert r.status_code == 200 and r.json()["cursor"]["running"] is True
    client.post("/api/connectors/historian/tick")
    latest = client.get("/api/connectors/historian/latest?n=5").json()
    assert [x["row_index"] for x in latest["rows"]] == [20, 21]
    assert latest["cursor"]["source_year"] == 2014
    assert client.post("/api/connectors/historian/stop").json()["cursor"]["running"] is False
    assert len(client.get("/api/connectors/historian/tags").json()["tags"]) == 11
    assert client.post("/api/connectors/historian/start", json={"year": 1999}).status_code == 422
    assert client.get("/api/connectors/historian/latest?n=0").status_code == 422


def test_cmms_and_notification_endpoints(client):
    assert client.get("/api/connectors/cmms/drafts").json()["drafts"] == []
    d = client.post("/api/connectors/cmms/drafts", json={"title": "Check AFDP trend", "case_id": "case_x"}).json()
    assert d["status"] == "DRAFT_NOT_SUBMITTED" and d["simulated"] is True
    listed = client.get("/api/connectors/cmms/drafts").json()
    assert listed["submit_supported"] is False and listed["drafts"][0]["id"] == d["id"]
    n = client.post("/api/connectors/notifications/send", json={"persona": "operator", "message": "hi"}).json()
    assert n["delivery"] == "in_app_simulated"
    out = client.get("/api/connectors/notifications/outbox").json()
    assert out["simulated"] is True and any(i["id"] == n["id"] for i in out["notifications"])
