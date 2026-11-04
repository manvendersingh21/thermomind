#!/usr/bin/env python
"""Live smoke test against the Meta Model API. Prints REDACTED JSON evidence; never the key.

Usage: cd /root/thermomind && . .venv/bin/activate && python scripts/meta_live_smoke.py
Exit codes: 0 ok, 1 call failed, 2 META not configured.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app import config  # noqa: E402
from app.agent._fake_case import make_fake_analysis  # noqa: E402
from app.agent.meta_client import MetaClient  # noqa: E402
from app.agent.orchestrator import run_investigation  # noqa: E402


def main() -> int:
    key = config.meta_api_key()
    if not key:
        print("META not configured")
        return 2
    client = MetaClient(key, config.META_BASE_URL, config.META_MODEL, config.META_TIMEOUT_S)
    out: dict = {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "base_url": config.META_BASE_URL, "model": config.META_MODEL}
    out["ping"] = client.ping()
    if not out["ping"]["ok"]:
        print(json.dumps(out, indent=1))
        return 1
    analysis = make_fake_analysis(synthetic=True)
    res = run_investigation(analysis, "synthetic_overlay", client, use_meta=True)
    tool_calls = [e for e in res.events if e.kind == "tool_call" and e.ok]
    model_turns = [e for e in res.events if e.kind == "model_response"]
    out.update({
        "status": res.status, "mode": res.mode, "meta_used": res.meta_used, "meta_model": res.meta_model,
        "latency_ms_total": sum(e.latency_ms or 0 for e in model_turns),
        "model_turns": len(model_turns),
        "tool_calls_made": [e.tool_name for e in tool_calls],
        "report_accepted": res.report is not None,
        "validation_errors": res.validation_errors,
        "rewrite_requested": any(e.kind == "rewrite_requested" for e in res.events),
        "first_pass_validation": [e.summary for e in res.events if e.kind == "validation"],
        "rewrite_reason": next((m.summary for m in res.events if m.kind == "rewrite_requested"), None),
        "token_usage": res.events[-1].tokens,
        "error": res.error,
    })
    if res.report:
        out["report_preview"] = {
            "title": res.report.title, "severity": res.report.severity,
            "hypotheses": [(h.rank, h.key or h.name, h.status) for h in sorted(res.report.hypotheses, key=lambda h: h.rank)],
            "n_observations": len(res.report.observations), "report_hash": res.report_hash,
        }
    print(json.dumps(out, indent=1, default=str))
    return 0 if res.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
