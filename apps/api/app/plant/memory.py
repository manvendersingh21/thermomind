"""Reviewed-precedent memory: "it keeps it in mind" = human review decisions on past cases.

Evidence signature = z-scores for a fixed list of evidence ids (missing -> 0). ``recall_similar`` ranks
stored investigations that carry a human review decision by cosine similarity of signatures. Precedents are
reviewed human decisions on similar evidence patterns — not ground truth, not verified fault labels.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

from app.plant.schemas import Precedent, PrecedentsResponse
from app.plant.work_requests import rank1_hypothesis

SIGNATURE_IDS = ["ev_afdp_01", "ev_afdp_02", "ev_tey_residual_01", "ev_tey_residual_02", "ev_cdp_01",
                 "ev_tit_01", "ev_tat_01", "ev_gtep_01", "ev_at_01", "ev_ah_01", "ev_ap_01"]
REVIEWED_DECISIONS = {"accepted", "rejected", "more_data_requested"}
Z_CLIP = 10.0  # keep one extreme z from dominating the cosine


def signature(evidence: Iterable[Any]) -> list[float]:
    by_id = {}
    for e in evidence or []:
        eid = e.get("evidence_id") if isinstance(e, dict) else getattr(e, "evidence_id", None)
        z = e.get("z_score") if isinstance(e, dict) else getattr(e, "z_score", None)
        by_id[eid] = z
    out = []
    for eid in SIGNATURE_IDS:
        z = by_id.get(eid)
        try:
            z = float(z)
        except (TypeError, ValueError):
            z = 0.0
        out.append(max(-Z_CLIP, min(Z_CLIP, z)) if math.isfinite(z) else 0.0)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _store_list() -> list[Any]:
    from app import services

    return services.get_store().list()


def recall_similar(case_id: Optional[str] = None, evidence: Optional[Iterable[Any]] = None, k: int = 3,
                   investigations: Optional[list[Any]] = None) -> PrecedentsResponse:
    """Top-k reviewed precedents for a case (by id) or an evidence list. Raises KeyError for unknown case."""
    invs = investigations if investigations is not None else _store_list()
    if evidence is None:
        if not case_id:
            raise ValueError("case_id or evidence is required")
        match = next((i for i in invs if i.case_id == case_id), None)
        if match is None:
            raise KeyError(f"investigation '{case_id}' not found")
        evidence = match.evidence
    query = signature(evidence)
    reviewed = [i for i in invs if i.review is not None and i.review.decision in REVIEWED_DECISIONS
                and i.case_id != case_id]
    scored = []
    for inv in reviewed:
        sim = cosine(query, signature(inv.evidence))
        scored.append(Precedent(
            case_id=inv.case_id, scenario_id=inv.scenario.scenario_id, scenario_label=inv.scenario_label,
            synthetic=bool(inv.scenario.synthetic), rank1_hypothesis=rank1_hypothesis(inv),
            decision=inv.review.decision, reviewer=inv.review.reviewer, comment=inv.review.comment,
            reviewed_at_utc=inv.review.ts_utc, similarity=round(sim, 4)))
    scored.sort(key=lambda p: -p.similarity)
    return PrecedentsResponse(case_id=case_id, signature_ids=list(SIGNATURE_IDS),
                              precedents=scored[:max(1, int(k))], reviewed_cases_considered=len(reviewed))
