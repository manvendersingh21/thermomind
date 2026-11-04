"""Agent organisation tree: registry shape, permissions, guarded stats, endpoint shape (test-local app)."""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app import config
from app.features.agents_tree import registry
from app.features.agents_tree import router as router_module


def _flat(node):
    yield node
    for c in node["children"]:
        yield from _flat(c)


@pytest.fixture()
def tree():
    return registry.build_tree(stats={})


def test_package_exports_router_module():
    assert hasattr(router_module, "router")
    assert isinstance(router_module.router, APIRouter)
    assert router_module.router.prefix == "/agents"


def test_registry_shape_and_unique_ids():
    reg = registry.build_registry()
    ids = [e["id"] for e in reg]
    assert len(ids) == len(set(ids))
    assert [e for e in reg if e["parent"] is None][0]["id"] == "root"
    for e in reg:
        assert e["kind"] in registry.KINDS
        assert e["name"] and e["description"]
        assert e["parent"] is None or e["parent"] in ids
    kinds = {e["kind"] for e in reg}
    assert {"llm_agent", "tool", "engine", "validator", "human", "model"} <= kinds


def test_expected_branches_present(tree):
    names = {n["name"] for n in _flat(tree)}
    assert "Investigation agent (Muse Spark, tool loop)" in names
    assert "Plant what-if aggregator" in names
    assert "Shift-handover drafter" in names and "Grid-event drill agent" in names
    assert "GPU second-opinion model (mlp_v1)" in names
    for tool in ("get_sensor_window", "get_baseline_comparison", "evaluate_hypothesis", "get_data_quality",
                 "list_evidence", "lookup_reference", "recall_similar_cases"):
        assert tool in names
    from app.plant.subsystems import SUBSYSTEM_REGISTRY
    sub_nodes = [n for n in _flat(tree) if n["id"].startswith("agent.whatif.")]
    assert len(sub_nodes) == len(SUBSYSTEM_REGISTRY) == 5
    for n in sub_nodes:
        assert n["meta"]["measurements"] and n["meta"]["owner_persona"]
        assert {"tool.simulate_change", "tool.get_sensor_window"} <= set(n["may_call"])


def test_every_llm_node_has_model_and_budget(tree):
    llm = [n for n in _flat(tree) if n["kind"] == "llm_agent"]
    assert len(llm) >= 9
    for n in llm:
        assert n["model"] == config.META_MODEL, n["id"]
        assert n["budget"] and n["budget"].get("max_tokens", 0) > 0, n["id"]
        assert "max_tool_rounds" in n["budget"]
    for n in _flat(tree):
        if n["kind"] in ("tool", "engine", "validator", "group"):
            assert n["model"] is None, n["id"]


def test_every_node_says_no_plant_control_and_ids_resolve(tree):
    nodes = list(_flat(tree))
    ids = {n["id"] for n in nodes}
    for n in nodes:
        assert "no plant control" in n["permissions"], n["id"]
        assert set(n["may_call"]) <= ids, n["id"]
    assert all(c["id"] in tree["may_call"] for c in tree["children"])


def test_n_plus_one_registry_entry_adds_a_node():
    reg = registry.build_registry()
    reg.append(registry._e("engine.extra", "group.engines", "Extra engine", "engine", "demo"))
    root = registry.build_tree(reg, {})
    assert any(n["id"] == "engine.extra" for n in _flat(root))


def test_stats_with_missing_db_are_zeros(tmp_path):
    stats = registry.collect_stats(tmp_path / "nope.db")
    assert stats["investigations"]["investigations"] == 0
    assert stats["whatif"]["sessions"] == 0 and stats["handover"]["notes"] == 0 and stats["grid_drills"]["drills"] == 0
    root = registry.build_tree(stats=stats)
    inv = next(n for n in _flat(root) if n["id"] == "agent.investigation")
    assert inv["stats"]["investigations"] == 0 and inv["stats"]["median tool calls / live case"] == 0
    wi = next(n for n in _flat(root) if n["id"] == "agent.whatif.intake")
    assert wi["stats"] == {"runs": 0, "ok rate": None}
    assert registry.totals(root)["stored_investigations"] == 0


def test_stats_with_empty_tables_and_unrelated_db(tmp_path):
    p = tmp_path / "empty.db"
    sqlite3.connect(p).execute("CREATE TABLE other (x)").connection.commit()
    payload = registry.tree_payload(p)
    assert payload["totals"]["stored_investigations"] == 0
    assert payload["root"]["children"]


def test_stats_from_stored_rows(tmp_path):
    p = tmp_path / "s.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE investigations (case_id TEXT, json TEXT)")
    c.execute("CREATE TABLE whatif_sessions (session_id TEXT, json TEXT)")
    c.execute("CREATE TABLE handover_notes (note_id TEXT, mode TEXT, json TEXT)")
    live = {"mode": "meta_live", "review": {"decision": "accepted"},
            "events": [{"kind": "tool_call", "tool_name": "list_evidence"}, {"kind": "tool_call", "tool_name": "get_sensor_window"},
                       {"kind": "tool_result", "tool_name": "list_evidence"}]}
    live2 = {"mode": "meta_live", "events": [{"kind": "tool_call", "tool_name": "list_evidence"}] * 4}
    off = {"mode": "offline_preview", "events": []}
    for i, d in enumerate((live, live2, off)):
        c.execute("INSERT INTO investigations VALUES (?,?)", (f"c{i}", json.dumps(d)))
    c.execute("INSERT INTO whatif_sessions VALUES ('w1', ?)", (json.dumps(
        {"mode": "meta_live", "status": "completed",
         "agents": [{"agent": "intake", "ok": True}, {"agent": "compressor", "ok": False}, {"agent": "aggregator", "ok": True}]}),))
    c.execute("INSERT INTO handover_notes VALUES ('h1','meta_live','{}')")
    c.commit()
    c.close()
    s = registry.collect_stats(p)
    assert s["investigations"]["investigations"] == 3
    assert s["investigations"]["live (Muse Spark)"] == 2
    assert s["investigations"]["median tool calls / live case"] == 3.0
    assert s["tool:list_evidence"]["calls in stored cases"] == 5
    assert s["review"]["accepted"] == 1
    assert s["subsystem:intake"]["ok rate"] == 1.0 and s["subsystem:compressor"]["ok rate"] == 0.0
    assert "subsystem:aggregator" not in s
    assert s["handover"]["notes"] == 1 and s["handover"]["live (Muse Spark)"] == 1
    assert s["grid_drills"] == {"drills": 0, "live (Muse Spark)": 0, "offline": 0}  # table missing -> zeros


def test_endpoint_shape_on_test_local_app(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    r = TestClient(app).get("/api/agents/tree")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"generated_at_utc", "root", "totals", "disclaimer"}
    assert body["generated_at_utc"].endswith("Z")
    assert body["root"]["id"] == "root" and body["root"]["children"]
    assert "read-only" in body["disclaimer"].lower()
    t = body["totals"]
    assert t["nodes"] == sum(1 for _ in _flat(body["root"]))
    assert t["by_kind"]["llm_agent"] == t["llm_agents"] >= 9
    for key in ("id", "name", "kind", "model", "may_call", "permissions", "budget", "stats", "children"):
        assert key in body["root"]
    assert "sk-" not in r.text and "MODEL_API_KEY" not in r.text
