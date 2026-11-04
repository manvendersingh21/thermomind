"""GET /instruments/scorecard (mounted under /api by the principal)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import services
from app.features.instruments import engine
from app.features.instruments.schemas import Scorecard
from app.schemas import SampleRange

router = APIRouter(prefix="/instruments", tags=["instruments"])

MIN_WINDOW_ROWS = 24


@router.get("/scorecard", response_model=Scorecard)
def scorecard(
    dataset_id: str = Query(services.UCI_DATASET_ID),
    year: int = Query(...),
    start: int | None = Query(None, description="window start row_index (inclusive); default 0"),
    end: int | None = Query(None, description="window end row_index (exclusive); default end of year"),
) -> Scorecard:
    try:
        bundle = services.get_repo().get(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "dataset not found")
    yf = bundle.year_frame(year)
    n = len(yf)
    if n == 0:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' has no rows for year {year}")
    s = 0 if start is None else start
    e = n if end is None else end
    if s < 0 or e > n or e <= s:
        raise HTTPException(status_code=422, detail=f"window [{s}, {e}) is invalid for year {year} (0..{n} rows available; need 0 <= start < end <= {n})")
    if e - s < MIN_WINDOW_ROWS:
        raise HTTPException(status_code=422, detail=f"window must contain at least {MIN_WINDOW_ROWS} rows (got {e - s})")
    window = yf.iloc[s:e].reset_index(drop=True)
    frame = bundle.frame
    train = frame[frame["source_year"].isin(engine.TRAIN_YEARS)]
    model = services.get_model()
    ranges = model.evaluation.feature_ranges_train if model is not None else None
    label = f"{year} samples #{s}-#{e - 1}" if (start is not None or end is not None) else f"year {year}"
    sensors, summary = engine.compute_scorecard(window, train, ranges, label)
    notes = list(engine.METHOD_NOTES)
    if not len(train):
        notes.append("No 2011-2013 rows in this dataset: out-of-range (TEY/CO/NOX) and coupling checks are unavailable.")
    if model is None:
        notes.append("Baseline model not loaded: feature ranges were computed from the 2011-2013 rows instead of model.feature_ranges_train.")
    return Scorecard(
        dataset_id=dataset_id, year=year,
        window=SampleRange(source_year=year, start=s, end=e),
        sensors=sensors, summary=summary, computed_at_utc=services.now_utc(), method_notes=notes,
    )
