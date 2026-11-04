"""Dataset endpoints: list, seed-uci, upload, detail, series."""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from app import config, services
from app.schemas import (
    MEASUREMENT_KEYS,
    TARGET_KEY,
    DatasetDetail,
    DatasetSummary,
    SeriesResponse,
    UploadResult,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
log = logging.getLogger("thermomind.api.datasets")


@router.get("", response_model=list[DatasetSummary])
def list_datasets() -> list[DatasetSummary]:
    return services.get_repo().list()


@router.post("/seed-uci", response_model=DatasetSummary)
def seed_uci() -> DatasetSummary:
    """Idempotent: loads the local raw UCI files (never downloads)."""
    raw_dir = Path(config.RAW_UCI_DIR)
    if not services.uci_raw_files_present(raw_dir):
        raise HTTPException(
            status_code=409,
            detail=f"UCI raw files not present in {raw_dir}; run `make data` (scripts/fetch_uci.py) first",
        )
    bundle = services.get_repo().seed_uci(raw_dir)
    return bundle.summary()


@router.post("/upload", response_model=UploadResult)
async def upload_dataset(file: UploadFile = File(...)) -> UploadResult:
    from app.data.uci_loader import load_csv_files
    from app.data.validator import CsvValidationError

    max_bytes = int(config.MAX_UPLOAD_BYTES)
    declared = getattr(file, "size", None)
    if declared is not None and declared > max_bytes:
        raise HTTPException(status_code=413, detail=f"file is {declared:,} bytes, larger than the {max_bytes:,} byte limit")

    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file is larger than the {max_bytes:,} byte limit")
    filename = file.filename or "upload.csv"

    def _load():
        return load_csv_files([(filename, data)], source="USER_UPLOAD")

    try:
        bundle = await run_in_threadpool(_load)
    except CsvValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    bundle = services.get_repo().register(bundle)
    log.info("upload registered: %s (%d rows, %s)", bundle.dataset_id, len(bundle.frame), filename)
    return UploadResult(
        dataset_id=bundle.dataset_id,
        rows=int(len(bundle.frame)),
        columns=list(MEASUREMENT_KEYS),
        source=bundle.source,
        sha256=bundle.source_files[0].sha256 if bundle.source_files else "",
        warnings=list(bundle.warnings),
    )


@router.get("/{dataset_id}", response_model=DatasetDetail)
def dataset_detail(dataset_id: str) -> DatasetDetail:
    return services.get_repo().get(dataset_id).detail()


@router.get("/{dataset_id}/series", response_model=SeriesResponse)
def dataset_series(
    dataset_id: str,
    measure: str = Query("TEY"),
    year: int = Query(2014),
    start: int = Query(0, ge=0),
    limit: int = Query(500, ge=1),
    include_expected: bool = Query(False),
) -> SeriesResponse:
    measure = measure.strip().upper()
    if measure not in MEASUREMENT_KEYS:
        raise HTTPException(
            status_code=422, detail=f"unknown measure '{measure}' (expected one of {', '.join(MEASUREMENT_KEYS)})"
        )
    repo = services.get_repo()
    resp = repo.series(dataset_id, measure, year, start, limit, max_points=config.MAX_SERIES_POINTS)

    if include_expected and measure == TARGET_KEY and resp.points:
        model = services.get_model()
        if model is not None:
            # expected TEY is MODEL-DERIVED; observed values stay real observations.
            bundle = repo.get(dataset_id)
            frame = bundle.window(year, resp.start, resp.end)
            preds = model.predict(frame)
            by_row = {int(r): float(p) for r, p in zip(frame["row_index"].to_numpy(), preds)}
            for pt in resp.points:
                val = by_row.get(pt.row_index)
                pt.expected = val if (val is not None and math.isfinite(val)) else None
    return resp
