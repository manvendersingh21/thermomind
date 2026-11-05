"""Optional physics rehearsal of the proposed change on ``app.simulator`` (built by another workflow).

Guarded duck-typing: the simulator is used only if it is importable AND exposes a service with an engine that
offers a recognised entry point. Otherwise ``status="unavailable"`` with the reason. A rehearsal runs the
software model only — it never touches a plant system.
"""
from __future__ import annotations

import importlib
import json
import logging
from typing import Any

from app.features.deliberation.schemas import ModelledChange, Rehearsal

log = logging.getLogger("thermomind.deliberation.rehearsal")
MAX_STEPS = 120
ENTRY_POINTS = ("rehearse", "run_change", "simulate", "run")


def _service(sim: Any) -> Any:
    svc = getattr(sim, "service", None)
    if svc is None:
        try:
            svc = importlib.import_module(sim.__name__ + ".service")
        except Exception:  # noqa: BLE001
            return None
    for getter in ("get_service", "get"):
        fn = getattr(svc, getter, None)
        if callable(fn) and not hasattr(svc, "engine"):
            try:
                svc = fn()
                break
            except Exception:  # noqa: BLE001
                return None
    return svc


def _summarise(result: Any) -> str:
    if isinstance(result, dict):
        for k in ("summary", "outcome_summary", "outcome"):
            if isinstance(result.get(k), str):
                return result[k][:600]
        keys = ", ".join(list(result)[:8])
        return f"simulator returned {len(result)} fields ({keys})"
    if isinstance(result, str):
        return result[:600]
    return f"simulator returned {type(result).__name__}"


def try_rehearsal(change: ModelledChange, steps: int = 60) -> Rehearsal:
    steps = max(1, min(int(steps), MAX_STEPS))
    if not change.observable or not change.deltas:
        return Rehearsal(status="unavailable", reason="the proposed change has no observable measurement deltas")
    try:
        sim = importlib.import_module("app.simulator")
    except Exception as exc:  # noqa: BLE001
        return Rehearsal(status="unavailable",
                         reason=f"app.simulator is not importable ({type(exc).__name__}); the physics simulator is "
                                f"being built by another workflow")
    svc = _service(sim)
    engine = getattr(svc, "engine", None) if svc is not None else None
    if engine is None:
        return Rehearsal(status="unavailable", reason="app.simulator is importable but exposes no service with an engine")
    fn_name = next((n for n in ENTRY_POINTS if callable(getattr(engine, n, None))), None)
    if fn_name is None:
        return Rehearsal(status="unavailable",
                         reason=f"simulator engine has no recognised entry point (expected one of {ENTRY_POINTS})")
    deltas = {d.measurement: d.delta for d in change.deltas}
    try:
        fn = getattr(engine, fn_name)
        try:
            result = fn(deltas=deltas, steps=steps)
        except TypeError:
            result = fn(deltas, steps)
    except Exception as exc:  # noqa: BLE001
        log.info("rehearsal failed: %s", type(exc).__name__)
        return Rehearsal(status="unavailable", reason=f"simulator call {fn_name}() failed ({type(exc).__name__})")
    return Rehearsal(status="available", reason=f"app.simulator engine.{fn_name}() — software model only, "
                                                f"nothing reaches the plant", steps=steps,
                     outcome_summary=_summarise(result),
                     details=(json.loads(json.dumps(result, default=str))
                              if isinstance(result, dict) and len(str(result)) < 8000 else {}))
