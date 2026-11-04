"""Domino map: subsystems + measurements, physical flow order and historical statistical couplings.

Edges
* physical (directed): generic gas-turbine flow order intake → compressor → combustion/turbine → exhaust and
  generator. Background engineering knowledge, not plant-specific data.
* membership: measurement → the subsystem it primarily belongs to.
* statistical (undirected): Pearson |r| ≥ 0.4 over the training years (2011–2013), with the least-squares slope
  of target on source — statistical association, not causation.

Given a case, the implicated measurement is chosen from the rank-1 hypothesis and the evidence z-scores; the
"domino path" is a BFS from that measurement over membership + downstream physical edges. Given a what-if
change, ``plant.sensitivity.simulate_change`` annotates the expected ΔTEY (MODEL-DERIVED).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable, Optional

from app.features.collab.schemas import (DEPENDENCY_CAVEAT, DependencyGraph, GraphEdge, GraphNode, Implicated,
                                         WhatIfAnnotation)
from app.schemas import MEASUREMENT_KEYS, MEASUREMENTS

R_THRESHOLD = 0.4
SUBSYSTEM_LAYER = {"intake": 0, "compressor": 1, "combustion_turbine": 2, "exhaust_emissions": 3,
                   "generator_output": 3}
PRIMARY_SUBSYSTEM = {"AT": "intake", "AP": "intake", "AH": "intake", "AFDP": "intake", "CDP": "compressor",
                     "TIT": "combustion_turbine", "TAT": "combustion_turbine", "GTEP": "exhaust_emissions",
                     "CO": "exhaust_emissions", "NOX": "exhaust_emissions", "TEY": "generator_output"}
PHYSICAL_FLOW = [("intake", "compressor"), ("compressor", "combustion_turbine"),
                 ("combustion_turbine", "exhaust_emissions"), ("combustion_turbine", "generator_output")]
SIGNAL_IDS = ("ev_afdp_01", "ev_afdp_02", "ev_tey_residual_01", "ev_tey_residual_02", "ev_cdp_01", "ev_tit_01",
              "ev_tat_01", "ev_gtep_01", "ev_at_01", "ev_ah_01", "ev_ap_01")
HYPOTHESIS_CANDIDATES = {
    "intake_restriction": ("AFDP",),
    "sensor_issue": ("CDP", "AFDP", "TIT", "TAT"),
    "operating_condition": ("AT", "AP", "AH"),
}
# Read-only wording: review, compare, ask, confirm. Never an operating instruction.
WHAT_TO_CHECK = {
    "intake": ["Compare AFDP with the reference window and its trend on the case page.",
               "Ask the mechanical maintenance engineer whether a filter-house inspection is already planned "
               "(any field work needs supervisor approval and a permit).",
               "Review ambient AT / AH / AP first: an operating-condition explanation is common."],
    "compressor": ["Compare CDP with the reference window (CDP unit is as published and under validation).",
                   "Ask the I&C engineer to confirm the CDP transmitter calibration record.",
                   "Look upstream: does AFDP show a matching change?"],
    "combustion_turbine": ["Review the TIT / TAT evidence z-scores together with the TEY residual.",
                           "Confirm with the reliability engineer before any inspection is planned.",
                           "Notable hot-gas-path evidence is shared with OEM field service through the work "
                           "request (external, simulated)."],
    "exhaust_emissions": ["Review the CO / NOx window-vs-reference deviation (real rows).",
                          "Keep the environmental engineer informed when emissions deviate notably.",
                          "Read GTEP together with TAT."],
    "generator_output": ["Review the TEY residual (observed minus model-expected, MWh as published).",
                         "Ask the electrical engineer whether output-side records explain the change.",
                         "Remember TEY is the model target, not a model input."],
}


def _r(x: Any, nd: int = 3) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


# ----------------------------------------------------------------------------- providers (patched in tests)
def get_registry() -> list[dict]:
    from app.plant.subsystems import SUBSYSTEM_REGISTRY

    return list(SUBSYSTEM_REGISTRY)


def get_training_stats() -> Optional[dict[str, Any]]:
    try:
        from app.plant import sensitivity

        return sensitivity.training_stats()
    except Exception:  # noqa: BLE001 - map still renders without statistical edges
        return None


def simulate(measurement: str, delta: float, case_id: Optional[str]) -> dict[str, Any]:
    from app.plant import sensitivity

    return sensitivity.simulate_change(measurement, delta, base=sensitivity.resolve_base(case_id))


def _owner_label(pid: Optional[str]) -> Optional[str]:
    if not pid:
        return None
    try:
        from app.plant.personas import label

        return f"owner: {label(pid)}"
    except Exception:  # noqa: BLE001
        return f"owner: {pid}"


def _rank1(inv: Any) -> Optional[str]:
    try:
        from app.plant.work_requests import rank1_hypothesis

        return rank1_hypothesis(inv)
    except Exception:  # noqa: BLE001
        return None


def _base_measurement(metric: str) -> Optional[str]:
    head = (metric or "").split("_")[0].upper()
    return head if head in MEASUREMENT_KEYS else None


def implicated_from_case(inv: Any) -> Implicated:
    hyp = _rank1(inv) or "unknown"
    allowed = HYPOTHESIS_CANDIDATES.get(hyp)
    best: Optional[tuple[float, str, str]] = None
    for e in inv.evidence or []:
        if e.evidence_id not in SIGNAL_IDS or e.z_score is None:
            continue
        m = _base_measurement(e.metric)
        if m is None or (allowed and m not in allowed):
            continue
        z = abs(float(e.z_score))
        if best is None or z > best[0]:
            best = (z, m, e.evidence_id)
    if best is not None:
        m = best[1]
        reason = (f"rank-1 hypothesis '{hyp}'; largest |z| among its measurements is {best[2]} "
                  f"(|z|={best[0]:.2f})")
    else:
        m = allowed[0] if allowed else "TEY"
        reason = f"rank-1 hypothesis '{hyp}'; no z-scored evidence available, default measurement {m}"
    return Implicated(subsystem=PRIMARY_SUBSYSTEM.get(m, "generator_output"), measurement=m, reason=reason)


def build_graph(case_id: Optional[str] = None, measurement: Optional[str] = None, delta: Optional[float] = None,
                get_investigation: Optional[Callable[[str], Any]] = None) -> DependencyGraph:
    """Raises KeyError (404) for an unknown case, ValueError (422) for a bad measurement/delta."""
    if measurement is not None and measurement not in MEASUREMENT_KEYS:
        raise ValueError(f"measurement must be one of {MEASUREMENT_KEYS}")
    if delta is not None and measurement is None:
        raise ValueError("delta requires measurement")
    if delta is not None and not math.isfinite(float(delta)):
        raise ValueError("delta must be finite")
    inv = None
    if case_id:
        if get_investigation is None:
            from app import services

            get_investigation = services.get_store().get
        inv = get_investigation(case_id)  # KeyError -> 404

    registry = get_registry()
    nodes: dict[str, GraphNode] = {}
    max_layer = max(SUBSYSTEM_LAYER.values())
    for s in registry:
        key = s["key"]
        nodes[f"s:{key}"] = GraphNode(
            id=f"s:{key}", kind="subsystem", label=s.get("name", key), layer=SUBSYSTEM_LAYER.get(key, max_layer),
            subsystem=key, owner_persona=s.get("owner_persona"), owner_label=_owner_label(s.get("owner_persona")),
            description=s.get("description"), how_it_works=s.get("how_it_works") or None,
            what_to_check=list(WHAT_TO_CHECK.get(key, ["Review this subsystem's evidence on the case page and ask "
                                                        "its owner before acting."])))
    reg_keys = {s["key"] for s in registry}
    for m in MEASUREMENT_KEYS:
        sub = PRIMARY_SUBSYSTEM.get(m)
        if sub not in reg_keys:  # n+1: fall back to the first registry entry listing the measurement
            sub = next((s["key"] for s in registry if m in s.get("measurements", [])), None)
        if sub is None:
            continue
        snode = nodes[f"s:{sub}"]
        nodes[f"m:{m}"] = GraphNode(
            id=f"m:{m}", kind="measurement", label=m, layer=snode.layer, subsystem=sub,
            unit=MEASUREMENTS[m]["unit"], owner_persona=snode.owner_persona, owner_label=snode.owner_label,
            description=f"{MEASUREMENTS[m]['name']} ({MEASUREMENTS[m]['unit']}); part of {snode.label}.",
            how_it_works=snode.how_it_works, what_to_check=list(snode.what_to_check))

    edges: list[GraphEdge] = []
    for a, b in PHYSICAL_FLOW:
        if f"s:{a}" in nodes and f"s:{b}" in nodes:
            edges.append(GraphEdge(source=f"s:{a}", target=f"s:{b}", kind="physical",
                                   label="flow order (generic gas-turbine background)"))
    for nid, n in nodes.items():
        if n.kind == "measurement":
            edges.append(GraphEdge(source=nid, target=f"s:{n.subsystem}", kind="membership", label="measured in"))

    stats = get_training_stats()
    years: list[int] = []
    corr: dict[str, dict[str, float]] = {}
    if stats:
        years = [int(y) for y in stats.get("years", [])]
        corr = stats.get("corr", {}) or {}
        cov = stats.get("cov", {}) or {}
        ms = [m for m in MEASUREMENT_KEYS if f"m:{m}" in nodes and m in corr]
        for i, a in enumerate(ms):
            for b in ms[i + 1:]:
                r = _r(corr.get(a, {}).get(b))
                if r is None or abs(r) < R_THRESHOLD:
                    continue
                var_a = (cov.get(a, {}) or {}).get(a)
                slope = _r(cov[a][b] / var_a, 4) if var_a and b in cov.get(a, {}) else None
                edges.append(GraphEdge(
                    source=f"m:{a}", target=f"m:{b}", kind="statistical", r=r, slope=slope,
                    label=f"r={r:+.2f}" + (f" · slope {slope:+.3g} {b}/{a}" if slope is not None else "")
                          + " (statistical association, not causation)"))

    implicated: Optional[Implicated] = None
    if inv is not None:
        implicated = implicated_from_case(inv)
    elif measurement:
        implicated = Implicated(subsystem=nodes[f"m:{measurement}"].subsystem or "", measurement=measurement,
                                reason=f"what-if measurement {measurement} (no case selected)")

    path: list[str] = []
    if implicated is not None and f"m:{implicated.measurement}" in nodes:
        start = f"m:{implicated.measurement}"
        implicated = implicated.model_copy(update={"subsystem": nodes[start].subsystem or implicated.subsystem})
        adj: dict[str, list[str]] = {}
        for e in edges:
            if e.kind in ("membership", "physical"):  # directed: measurement -> subsystem -> downstream
                adj.setdefault(e.source, []).append(e.target)
        parent: dict[str, Optional[str]] = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            path.append(cur)
            for nxt in adj.get(cur, []):
                if nxt not in parent:
                    parent[nxt] = cur
                    q.append(nxt)
        tree = {(p, c) for c, p in parent.items() if p is not None}
        for e in edges:
            if (e.source, e.target) in tree:
                e.on_path = True
        for nid in path:
            nodes[nid].on_path = True
        nodes[start].implicated = True
        nodes[f"s:{implicated.subsystem}"].implicated = True
        for e in edges:
            if e.kind == "statistical" and start in (e.source, e.target):
                other = e.target if e.source == start else e.source
                nodes[other].stat_neighbour = True

    whatif: Optional[WhatIfAnnotation] = None
    if measurement is not None and delta is not None:
        res = simulate(measurement, float(delta), case_id)  # ValueError -> 422
        me = res.get("model_effect", {}) or {}
        trc = res.get("train_range_check", {}) or {}
        whatif = WhatIfAnnotation(
            measurement=measurement, delta=float(res.get("delta", delta)), unit=str(res.get("unit", "")),
            applicable=bool(me.get("applicable")), delta_tey_mean=_r(me.get("delta_tey_mean"), 4),
            delta_tey_min=_r(me.get("delta_tey_min"), 4), delta_tey_max=_r(me.get("delta_tey_max"), 4),
            ood_flag=trc.get("ood_flag"), note=str(me.get("note") or ""))

    return DependencyGraph(nodes=list(nodes.values()), edges=edges, implicated=implicated, domino_path=path,
                           whatif=whatif, caveat=DEPENDENCY_CAVEAT, threshold=R_THRESHOLD, training_years=years,
                           case_id=case_id or None, synthetic=(bool(inv.scenario.synthetic) if inv is not None else None))
