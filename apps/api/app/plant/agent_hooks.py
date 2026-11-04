"""Optional extra tools for the investigation orchestrator (``app.agent.orchestrator`` imports this if present).

Each entry: {"spec": OpenAI function-tool JSON, "handler": callable(analysis, args) -> (result, evidence_ids)}.
Precedent results never return citable evidence ids (they belong to other cases).
"""
from __future__ import annotations

from typing import Any

RECALL_SPEC = {
    "type": "function",
    "function": {
        "name": "recall_similar_cases",
        "description": (
            "Recall up to k previously investigated cases whose evidence z-score pattern is most similar to this "
            "case AND that carry a human review decision (accepted / rejected / more_data_requested), with the "
            "reviewer's comment. These are reviewed human decisions on similar evidence patterns, not ground "
            "truth; their evidence ids belong to other cases and must not be cited."
        ),
        "parameters": {"type": "object",
                       "properties": {"k": {"type": "integer", "minimum": 1, "maximum": 5,
                                            "description": "How many precedents (default 3)."}}},
    },
}

EXTRA_SYSTEM_NOTE = (
    "\n\nPrecedent memory: the tool recall_similar_cases returns reviewed human decisions on past cases with a "
    "similar evidence pattern (cosine similarity of z-score signatures). Use them only as context (e.g. 'a "
    "similar pattern was previously rejected by a reviewer because ...'); they are not ground truth, not "
    "verified fault labels, and their evidence ids must never be cited in this report."
)


def _recall_handler(analysis: Any, args: dict) -> tuple[dict, list[str]]:
    from app.agent.tools import ToolError
    from app.plant.memory import recall_similar

    extra = set(args or {}) - {"k"}
    if extra:
        raise ToolError(f"unexpected arguments for recall_similar_cases: {sorted(extra)}")
    k = (args or {}).get("k", 3)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 5:
        raise ToolError("k must be an integer in [1, 5]")
    try:
        resp = recall_similar(case_id=analysis.case_id, evidence=analysis.evidence, k=k)
    except Exception as exc:  # noqa: BLE001 - memory is optional context
        return {"available": False, "error": f"precedent store unavailable ({type(exc).__name__})"}, []
    out = resp.model_dump()
    out["available"] = True
    return out, []


EXTRA_TOOLS: list[dict[str, Any]] = [{"spec": RECALL_SPEC, "handler": _recall_handler}]
