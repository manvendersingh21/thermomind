"""Model endpoints: evaluation (404 until trained) and local train."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import config, services
from app.schemas import ModelEvaluation

router = APIRouter(prefix="/models", tags=["models"])
log = logging.getLogger("thermomind.api.models")


class TrainRequest(BaseModel):
    seed: int | None = None


@router.get("/evaluation", response_model=ModelEvaluation)
def model_evaluation() -> ModelEvaluation:
    model = services.get_model(recheck=True)
    if model is None:
        raise HTTPException(status_code=404, detail="baseline model not trained yet (run `make train` or POST /api/models/train)")
    return model.evaluation


@router.post("/train", response_model=ModelEvaluation)
async def train_model(body: TrainRequest | None = Body(default=None)) -> ModelEvaluation:
    """Local/admin only: trains the baseline on ds_uci_551 and reloads it."""
    from app.analytics.train import train_baseline

    seed = 42 if body is None or body.seed is None else int(body.seed)
    bundle = services.get_repo().get(services.UCI_DATASET_ID)  # KeyError -> 404 if not seeded

    def _train() -> ModelEvaluation:
        return train_baseline(bundle.frame, Path(config.MODEL_DIR), seed=seed)

    log.info("training baseline model (seed=%d, rows=%d)", seed, len(bundle.frame))
    evaluation = await run_in_threadpool(_train)
    services.reload_model()
    return evaluation
