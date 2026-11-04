"""ThermoMind API — FastAPI application factory, error mapping, static SPA serving."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError

from app import config, services
from app.api import datasets, demo, health, investigations, models, scenarios

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("thermomind.main")

ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("ThermoMind API %s (%s) starting", config.APP_VERSION, config.BUILD)
    try:
        services.startup()
    except Exception as exc:  # noqa: BLE001 - degraded start is better than no start
        log.warning("startup incomplete: %s", type(exc).__name__)
    log.info(
        "data_ready=%s model_ready=%s meta_configured=%s",
        services.data_ready(), services.get_model() is not None, config.meta_configured(),
    )
    yield
    log.info("ThermoMind API shutting down")


app = FastAPI(title="ThermoMind API", version=config.APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health.router, demo.router, datasets.router, models.router, scenarios.router, investigations.router):
    app.include_router(router, prefix="/api")
from app.api import plant as _plant_api; app.include_router(_plant_api.router, prefix="/api")  # noqa: E402,E702 plant-ops


# ---------------------------------------------------------------------------
# Error mapping: never 500 for user-input problems, never leak secrets.
# ---------------------------------------------------------------------------


def _safe_detail(exc: Exception, fallback: str) -> str:
    text = str(exc).strip() or fallback
    key = config.meta_api_key()
    if key and key in text:
        text = text.replace(key, "[REDACTED]")
    return text[:500]


@app.exception_handler(KeyError)
async def _key_error(_: Request, exc: KeyError) -> JSONResponse:
    detail = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "not found"
    return JSONResponse(status_code=404, content={"detail": _safe_detail(ValueError(detail), "not found")})


@app.exception_handler(IndexError)
async def _index_error(_: Request, exc: IndexError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _safe_detail(exc, "index out of range")})


@app.exception_handler(PydanticValidationError)
async def _internal_validation_error(request: Request, exc: PydanticValidationError) -> JSONResponse:
    # pydantic.ValidationError subclasses ValueError, but reaching here means *internal* data (e.g. a stored row)
    # failed validation: request bodies are validated by FastAPI (RequestValidationError -> 422) before this.
    log.error("internal data validation error on %s %s (%d error(s))", request.method, request.url.path,
              exc.error_count())
    return JSONResponse(status_code=500, content={"detail": "internal data validation error; see server logs"})


@app.exception_handler(ValueError)
async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
    status = getattr(exc, "status_code", None)  # CsvValidationError carries its own HTTP status
    if not isinstance(status, int):
        status = 422
    message = getattr(exc, "message", None) or _safe_detail(exc, "invalid input")
    return JSONResponse(status_code=status, content={"detail": str(message)[:500]})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"internal error ({type(exc).__name__}); see server logs"},
    )


# ---------------------------------------------------------------------------
# Static SPA (apps/web/dist) with fallback for non-/api paths
# ---------------------------------------------------------------------------

_dist = Path(config.WEB_DIST)
if _dist.is_dir() and (_dist / "index.html").is_file():
    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="not found")
        candidate = (_dist / full_path).resolve() if full_path else None
        if candidate is not None and full_path and candidate.is_file() and str(candidate).startswith(str(_dist.resolve())):
            return FileResponse(str(candidate))
        return FileResponse(str(_dist / "index.html"))

    log.info("serving web UI from %s", _dist)
else:

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": "ThermoMind API", "version": config.APP_VERSION, "docs": "/docs", "health": "/api/health"}
