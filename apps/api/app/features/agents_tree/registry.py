"""Registry of ThermoMind's agents (n+1: adding an agent is appending one entry) plus live, guarded stats.

Registry entry shape (plain dict)::

    {"id": "engine.my_engine",          # unique, "<kind>.<slug>"
     "parent": "group.engines",          # id of the parent node (None only for the root)
     "name": "My engine",
     "kind": "llm_agent" | "tool" | "engine" | "validator" | "human" | "model" | "group",
     "model": "muse-spark-1.3" | None,   # LLM agents must name a model
     "description": "one sentence",
     "permissions": ["read-only data", "no plant control"],   # every node must include "no plant control"
     "budget": {"max_tokens": 3000, "max_tool_rounds": 1, "time_budget_s": 55} | None,   # required for llm_agent
     "calls": ["tool.simulate_change"],  # optional extra may_call ids that are not children
     "stats_key": "whatif",              # optional: which live-stats block this node shows
     "meta": {...}}                      # optional free facts (measurements, owner persona, ...)

Stats are read from the SQLite DB (``config.DB_PATH``) read-only; a missing file or table yields zeros.
Nothing here calls a model, writes to the DB, or touches any plant system.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app import config

log = logging.getLogger("thermomind.agents_tree")

MODEL = config.META_MODEL
NO_CONTROL = "no plant control"
RO = "read-only data"
DRAFT = "draft only"
KINDS = ("llm_agent", "tool", "engine", "validator", "human", "model", "group")  # "group" = pure grouping node
DISCLAIMER = ("Every agent is read-only and advisory. No agent has any path to PLC/SCADA/DCS/historian writes, "
              "setpoints or control commands; humans review and act per site procedures.")

INVESTIGATION_TOOLS = ["get_sensor_window", "get_baseline_comparison", "evaluate_hypothesis", "get_data_quality",
                       "list_evidence", "lookup_reference", "recall_similar_cases"]
_TOOL_DESC = {
    "get_sensor_window": "Returns the (labelled) sensor window for the case, original rows plus any synthetic overlay.",
    "get_baseline_comparison": "Production baseline model expected TEY versus measured over the window (model-derived).",
    "evaluate_hypothesis": "Deterministic support check for one hypothesis against the evidence items.",
    "get_data_quality": "Data-quality report for the window (missing, flat-lined, out-of-range).",
    "list_evidence": "Lists the deterministic evidence items (ids the report may cite).",
    "lookup_reference": "Static background reference on a measurement or failure mode (generic, not plant-specific).",
    "recall_similar_cases": "Reviewed human decisions on past cases with a similar evidence pattern (precedent, not ground truth).",
}


def _e(id_: str, parent: Optional[str], name: str, kind: str, description: str, *, model: Optional[str] = None,
       permissions: Optional[list[str]] = None, budget: Optional[dict] = None, calls: Optional[list[str]] = None,
       stats_key: Optional[str] = None, meta: Optional[dict] = None) -> dict:
    return {"id": id_, "parent": parent, "name": name, "kind": kind, "model": model, "description": description,
            "permissions": permissions or [RO, NO_CONTROL], "budget": budget, "calls": calls or [],
            "stats_key": stats_key, "meta": meta or {}}


def _orch_limits() -> dict:
    try:
        from app.agent.orchestrator import TIME_BUDGET_S
    except Exception:  # noqa: BLE001
        TIME_BUDGET_S = 300.0
    return {"max_tokens": int(config.META_MAX_TOKENS), "max_tool_rounds": int(config.META_MAX_TOOL_ROUNDS),
            "time_budget_s": float(TIME_BUDGET_S)}


def _tool_names() -> list[str]:
    try:
        from app.agent.tools import TOOL_NAMES
        names = list(TOOL_NAMES)
    except Exception:  # noqa: BLE001
        names = INVESTIGATION_TOOLS[:6]
    if "recall_similar_cases" not in names:
        names.append("recall_similar_cases")
    return names


def _plant_limits() -> dict[str, Any]:
    try:
        from app.plant import whatif
        return {"max_tokens": whatif.MAX_TOKENS, "agg_max_tokens": whatif.AGGREGATOR_MAX_TOKENS,
                "budget_s": whatif.AGENT_BUDGET_S}
    except Exception:  # noqa: BLE001
        return {"max_tokens": 3000, "agg_max_tokens": 5000, "budget_s": 55.0}


def build_registry() -> list[dict]:
    """Flat registry; parents come before children. Subsystem agents and personas are read from their registries."""
    R: list[dict] = []
    add = R.append
    pl = _plant_limits()
    add(_e("root", None, "ThermoMind orchestrator (read-only; no control path)", "engine",
           "Routes a request to the right agent group and assembles the draft. It has no write path to any plant system.",
           permissions=[RO, DRAFT, NO_CONTROL]))

    # --- investigation agent
    add(_e("agent.investigation", "root", "Investigation agent (Muse Spark, tool loop)", "llm_agent",
           "Investigates one case through deterministic tools and writes a structured draft report with evidence ids.",
           model=MODEL, permissions=[RO, DRAFT, NO_CONTROL], budget=_orch_limits(), stats_key="investigations"))
    for t in _tool_names():
        add(_e(f"tool.{t}", "agent.investigation", t, "tool", _TOOL_DESC.get(t, "Deterministic tool."),
               stats_key="tool:" + t))
    add(_e("model.mlp_v1", "agent.investigation", "GPU second-opinion model (mlp_v1)", "model",
           "PyTorch MLP challenger for expected TEY; second opinion only, not the production model.",
           model="mlp_v1", permissions=[RO, "second opinion only", NO_CONTROL]))

    # --- plant what-if
    add(_e("agent.whatif", "root", "Plant what-if aggregator", "llm_agent",
           "Runs one agent per plant subsystem in parallel, then merges them into cross-impacts and next steps.",
           model=MODEL, permissions=[RO, DRAFT, NO_CONTROL],
           budget={"max_tokens": pl["agg_max_tokens"], "max_tool_rounds": 0, "time_budget_s": None},
           stats_key="whatif"))
    add(_e("tool.simulate_change", "agent.whatif", "simulate_change", "tool",
           "Shifts one measurement and re-runs the baseline model (model-derived, ceteris paribus) plus historical co-movement.",
           stats_key="whatif_tool"))
    try:
        from app.plant.subsystems import SUBSYSTEM_REGISTRY
        subs = list(SUBSYSTEM_REGISTRY)
    except Exception:  # noqa: BLE001
        subs = []
    for s in subs:
        add(_e(f"agent.whatif.{s['key']}", "agent.whatif", f"{s['name']} agent", "llm_agent", s.get("description", ""),
               model=MODEL, permissions=[RO, DRAFT, NO_CONTROL],
               budget={"max_tokens": pl["max_tokens"], "max_tool_rounds": 1, "time_budget_s": pl["budget_s"]},
               calls=["tool.simulate_change", "tool.get_sensor_window", "tool.lookup_reference"],
               stats_key="subsystem:" + s["key"],
               meta={"subsystem": s["key"], "measurements": list(s.get("measurements", [])),
                     "owner_persona": s.get("owner_persona"), "tools": ["simulate_change", "get_sensor_window", "lookup_reference"]}))

    # --- operations agents
    add(_e("group.ops", "root", "Operations agents", "group", "LLM drafters for operations workflows; drafts only.",
           permissions=[RO, DRAFT, NO_CONTROL]))
    add(_e("agent.handover", "group.ops", "Shift-handover drafter", "llm_agent",
           "Drafts a shift-handover note from stored investigations and open work requests.",
           model=MODEL, permissions=[RO, DRAFT, NO_CONTROL],
           budget={"max_tokens": _int_env("OPS_HANDOVER_MAX_TOKENS", 10000), "max_tool_rounds": 0, "time_budget_s": None},
           stats_key="handover"))
    add(_e("agent.grid_drill", "group.ops", "Grid-event drill agent", "llm_agent",
           "Applies a labelled synthetic grid event (S05) to a copy of the window and drafts a drill brief.",
           model=MODEL, permissions=[RO, DRAFT, "synthetic overlay only", NO_CONTROL],
           budget={"max_tokens": 9000, "max_tool_rounds": 0, "time_budget_s": None}, stats_key="grid_drills"))

    # --- deterministic engines
    add(_e("group.engines", "root", "Deterministic screening engines (no LLM)", "group",
           "Plain code: same input, same output. They produce the numbers the LLM agents may cite.", stats_key=None))
    for id_, name, desc in [
        ("engine.evidence", "Evidence engine", "Window-versus-reference statistics, baseline comparison, hypothesis support."),
        ("engine.instruments", "Instrument health", "Flags suspect sensors from flat-lines, spikes, drift and cross-checks."),
        ("engine.emissions", "Emissions watch", "CO / NOx behaviour against the plant's own history; screening only, not compliance."),
        ("engine.thermal", "Thermal model", "Simplified Brayton-cycle consistency check; model-derived, not a guarantee test."),
        ("engine.planner", "Maintenance planner", "Ranks maintenance windows from stored cases; a draft for planners."),
        ("engine.grid", "Grid readiness / contingency", "Readiness cards and N-1-style what-if on public data; screening only."),
    ]:
        add(_e(id_, "group.engines", name, "engine", desc))

    # --- validators and humans
    add(_e("group.validators", "root", "Validators & humans", "group",
           "Gates between a draft and a person. Nothing is released as final.", permissions=[RO, NO_CONTROL]))
    add(_e("validator.report", "group.validators", "Report validator", "validator",
           "Checks report schema, evidence-id citations and fixed wording; allows one bounded rewrite."))
    add(_e("validator.unsafe", "group.validators", "Unsafe-pattern scan", "validator",
           "Scans all free text for control-style instructions and fabricated dates; failures are rewritten or replaced."))
    add(_e("human.review", "group.validators", "Human review (per site procedures)", "human",
           "A person accepts, rejects or asks for more data; they decide and act under site procedures.",
           permissions=[RO, "decides and acts per site procedures", NO_CONTROL], stats_key="review"))
    try:
        from app.plant.personas import PERSONAS
        for pid, p in PERSONAS.items():
            add(_e(f"human.persona.{pid}", "human.review", p.role, "human",
                   f"Demo persona '{pid}' (no authentication, simulated in-app notifications).",
                   permissions=[RO, "decides and acts per site procedures", NO_CONTROL],
                   meta={"persona_id": pid}))
    except Exception:  # noqa: BLE001
        pass
    return R


def _int_env(name: str, default: int) -> int:
    import os
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# ----------------------------------------------------------------------------- stats (read-only, guarded)
def _connect_ro(db_path: Path) -> Optional[sqlite3.Connection]:
    try:
        if not Path(db_path).is_file():
            return None
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("PRAGMA query_only=ON")
        return conn
    except Exception:  # noqa: BLE001
        return None


def _rows(conn: Optional[sqlite3.Connection], sql: str) -> list[tuple]:
    if conn is None:
        return []
    try:
        return conn.execute(sql).fetchall()
    except Exception:  # noqa: BLE001 - missing table / corrupt db -> zeros
        return []


def _json(raw: Any) -> dict:
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def collect_stats(db_path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Return {stats_key: {chip label: value}}. Never raises; missing tables give zeros."""
    conn = _connect_ro(Path(db_path or config.DB_PATH))
    out: dict[str, dict[str, Any]] = {}
    try:
        # investigations
        inv = [_json(r[0]) for r in _rows(conn, "SELECT json FROM investigations")]
        live = sum(1 for i in inv if i.get("mode") == "meta_live")
        per_case: list[int] = []
        tool_counts: Counter = Counter()
        for i in inv:
            n = 0
            for ev in i.get("events") or []:
                if isinstance(ev, dict) and ev.get("kind") == "tool_call":
                    n += 1
                    if ev.get("tool_name"):
                        tool_counts[ev["tool_name"]] += 1
            if i.get("mode") == "meta_live":
                per_case.append(n)
        med = statistics.median(per_case) if per_case else 0
        out["investigations"] = {"investigations": len(inv), "live (Muse Spark)": live,
                                 "offline preview": len(inv) - live,
                                 "median tool calls / live case": float(med) if per_case else 0}
        for t in set(_tool_names()) | set(tool_counts):
            out["tool:" + t] = {"calls in stored cases": int(tool_counts.get(t, 0))}
        reviewed = Counter((i.get("review") or {}).get("decision") for i in inv if i.get("review"))
        out["review"] = {"cases reviewed": sum(reviewed.values()),
                         **{str(k): v for k, v in sorted(reviewed.items(), key=lambda kv: str(kv[0]))}}
        # what-if
        sessions = [_json(r[0]) for r in _rows(conn, "SELECT json FROM whatif_sessions")]
        per_sub: dict[str, list[int]] = {}
        for s in sessions:
            for a in s.get("agents") or []:
                if isinstance(a, dict) and a.get("agent") and a.get("agent") != "aggregator":
                    per_sub.setdefault(a["agent"], []).append(1 if a.get("ok") else 0)
        out["whatif"] = {"sessions": len(sessions),
                         "live (Muse Spark)": sum(1 for s in sessions if s.get("mode") == "meta_live"),
                         "offline": sum(1 for s in sessions if s.get("mode") == "offline"),
                         "needs review": sum(1 for s in sessions if s.get("status") == "needs_review")}
        out["whatif_tool"] = {"sessions using it": len(sessions)}
        for key in {k for k in per_sub}:
            vals = per_sub[key]
            out["subsystem:" + key] = {"runs": len(vals), "ok rate": round(sum(vals) / len(vals), 3)}
        # handover and grid drills
        for key, table in (("handover", "handover_notes"), ("grid_drills", "grid_drills")):
            modes = Counter(r[0] for r in _rows(conn, f"SELECT mode FROM {table}"))
            n = sum(modes.values())
            out[key] = {"notes" if key == "handover" else "drills": n,
                        "live (Muse Spark)": modes.get("meta_live", 0), "offline": n - modes.get("meta_live", 0)}
    except Exception as exc:  # noqa: BLE001
        log.warning("agents_tree stats failed: %s", type(exc).__name__)
    finally:
        if conn is not None:
            conn.close()
    return out


# ----------------------------------------------------------------------------- tree
def _zero_stats(key: str) -> dict[str, Any]:
    if key == "investigations":
        return {"investigations": 0, "live (Muse Spark)": 0, "offline preview": 0, "median tool calls / live case": 0}
    if key.startswith("tool:"):
        return {"calls in stored cases": 0}
    if key == "review":
        return {"cases reviewed": 0}
    if key == "whatif":
        return {"sessions": 0, "live (Muse Spark)": 0, "offline": 0, "needs review": 0}
    if key == "whatif_tool":
        return {"sessions using it": 0}
    if key.startswith("subsystem:"):
        return {"runs": 0, "ok rate": None}
    if key == "handover":
        return {"notes": 0, "live (Muse Spark)": 0, "offline": 0}
    if key == "grid_drills":
        return {"drills": 0, "live (Muse Spark)": 0, "offline": 0}
    return {}


def node_dict(entry: dict, stats: dict[str, dict[str, Any]]) -> dict:
    key = entry.get("stats_key")
    node_stats = dict(stats.get(key) or _zero_stats(key)) if key else {}
    return {"id": entry["id"], "name": entry["name"], "kind": entry["kind"], "model": entry["model"],
            "description": entry["description"], "permissions": list(entry["permissions"]),
            "budget": entry["budget"], "may_call": list(entry["calls"]), "stats": node_stats,
            "meta": entry["meta"], "children": []}


def build_tree(registry: Optional[list[dict]] = None, stats: Optional[dict] = None) -> dict:
    reg = registry if registry is not None else build_registry()
    stats = stats if stats is not None else collect_stats()
    nodes = {e["id"]: node_dict(e, stats) for e in reg}
    root = None
    for e in reg:
        n = nodes[e["id"]]
        if e["parent"] is None:
            root = n
        else:
            parent = nodes[e["parent"]]  # KeyError on a bad registry entry is a programming error (tested)
            parent["children"].append(n)
            parent["may_call"].append(n["id"])
    if root is None:
        raise ValueError("registry has no root entry")
    return root


def _walk(n: dict):
    yield n
    for c in n["children"]:
        yield from _walk(c)


def totals(root: dict) -> dict:
    nodes = list(_walk(root))
    by_kind = Counter(n["kind"] for n in nodes)
    llm = [n for n in nodes if n["kind"] == "llm_agent"]
    return {"nodes": len(nodes), "by_kind": {k: by_kind.get(k, 0) for k in KINDS},
            "llm_agents": len(llm), "deterministic_nodes": len(nodes) - len(llm),
            "subsystem_agents": sum(1 for n in nodes if n["id"].startswith("agent.whatif.")),
            "stored_investigations": next((n["stats"].get("investigations", 0) for n in nodes
                                           if n["id"] == "agent.investigation"), 0)}


def tree_payload(db_path: Optional[Path] = None) -> dict:
    root = build_tree(stats=collect_stats(db_path))
    return {"generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "root": root, "totals": totals(root), "disclaimer": DISCLAIMER}
