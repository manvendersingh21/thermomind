"""Run one REAL multi-agent what-if against Muse Spark and print a JSON summary + timings.

Usage: python scripts/whatif_live.py [case_id] [measurement] [delta]
(defaults: case_76d34565b3dc AFDP 1.0). Needs MODEL_API_KEY/MUSE_API_KEY in .env; never prints the key.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import services  # noqa: E402
from app.plant.schemas import WhatIfRequest  # noqa: E402
from app.plant.whatif import run_whatif  # noqa: E402


def main() -> None:
    case_id = sys.argv[1] if len(sys.argv) > 1 else "case_76d34565b3dc"
    meas = sys.argv[2] if len(sys.argv) > 2 else "AFDP"
    delta = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    services.startup()
    client = services.get_meta_client()
    print(f"meta configured: {client.configured}; model: {client.model}", flush=True)
    req = WhatIfRequest(case_id=case_id, measurement=meas, delta=delta, persona="mechanical_maintenance_engineer",
                        question=f"If the intake filter differential pressure ({meas}) rises by {delta:+g} mbar during "
                                 "my filter-house work, how does that impact the rest of the plant?")
    t0 = time.perf_counter()
    s = run_whatif(req, client if client.configured else None)
    wall = time.perf_counter() - t0
    out = {
        "session_id": s.session_id, "status": s.status, "mode": s.mode, "meta_used": s.meta_used,
        "meta_model": s.meta_model, "wall_s": round(wall, 1), "validation_errors": s.validation_errors,
        "agents": [{"agent": a.agent, "ok": a.ok, "used_tools": a.used_tools, "model_latency_ms": a.latency_ms,
                    "tokens": a.tokens, "tool_calls": [e.summary for e in a.events if e.kind == "tool_call"],
                    "error": a.error} for a in s.agents],
        "deterministic": {"model_effect": s.sensitivity["model_effect"],
                          "train_range_check": s.sensitivity["train_range_check"]},
        "answer": s.answer.model_dump() if s.answer else None,
    }
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
