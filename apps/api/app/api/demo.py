"""GET /api/demo/status — readiness overview for the demo (key is never included)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app import config, services
from app.schemas import DemoStatus

router = APIRouter(tags=["demo"])
log = logging.getLogger("thermomind.api.demo")


@router.get("/demo/status", response_model=DemoStatus)
def demo_status() -> DemoStatus:
    blockers: list[str] = []

    # --- data ------------------------------------------------------------------------
    data: dict[str, Any] = {
        "ready": False,
        "dataset_id": services.UCI_DATASET_ID,
        "raw_dir": str(config.RAW_UCI_DIR),
        "raw_files_present": services.uci_raw_files_present(),
    }
    try:
        bundle = services.get_repo().get(services.UCI_DATASET_ID)
        data.update(ready=True, row_count=int(len(bundle.frame)), years=bundle.years(),
                    source=bundle.source, has_timestamps=False, warnings=len(bundle.warnings))
    except Exception as exc:  # noqa: BLE001
        data["error"] = f"{type(exc).__name__}"
        blockers.append("UCI dataset not loaded (run `make data` then restart or POST /api/datasets/seed-uci)")

    # --- model -----------------------------------------------------------------------
    model_obj = services.get_model(recheck=True)
    model: dict[str, Any] = {"ready": model_obj is not None, "model_dir": str(config.MODEL_DIR)}
    if model_obj is not None:
        ev = model_obj.evaluation
        model.update(
            model_version=ev.model_version,
            algorithm=ev.algorithm,
            holdout_mae=ev.holdout.mae,
            holdout_r2=ev.holdout.r2,
            validation_mae=ev.validation.mae,
            trained_at_utc=ev.trained_at_utc,
            split=ev.split.method,
        )
    else:
        blockers.append("baseline model not trained (run `make train`)")

    # --- meta ------------------------------------------------------------------------
    meta: dict[str, Any] = {
        "configured": config.meta_configured(),
        "model": config.META_MODEL,
        "base_url": config.META_BASE_URL,
        "timeout_s": config.META_TIMEOUT_S,
        "key_source": "MODEL_API_KEY/MUSE_API_KEY (server-side only, never returned)",
    }
    if not config.meta_configured():
        meta["note"] = "Meta key not set: investigations run as offline_preview only"

    # --- backend ---------------------------------------------------------------------
    backend: dict[str, Any] = {"version": config.APP_VERSION, "db_path": str(config.DB_PATH)}
    try:
        store = services.get_store()
        backend["investigations"] = store.count()
        latest = store.list()[:5]
        backend["latest_cases"] = [
            {"case_id": i.case_id, "status": i.status, "scenario_id": i.scenario.scenario_id,
             "mode": i.mode, "meta_used": i.meta_used, "created_at_utc": i.created_at_utc}
            for i in latest
        ]
    except Exception as exc:  # noqa: BLE001
        backend["error"] = type(exc).__name__
        blockers.append("investigation store unavailable")

    # --- scenarios ---------------------------------------------------------------------
    scenarios: dict[str, Any] = {}
    try:
        reg = services.get_scenarios()
        scenarios = {
            "count": len(reg),
            "ids": list(reg.keys()),
            "synthetic": [s.scenario_id for s in reg.values() if s.synthetic],
        }
    except Exception as exc:  # noqa: BLE001
        scenarios = {"count": 0, "error": type(exc).__name__}
        blockers.append("scenario registry unavailable (app.analytics.scenarios)")

    build = {"version": config.APP_VERSION, "build": config.BUILD, "web_dist_present": config.WEB_DIST.is_dir()}

    return DemoStatus(
        data=data,
        model=model,
        meta=meta,
        backend=backend,
        scenarios=scenarios,
        build=build,
        ready_for_demo=not blockers,
        blockers=blockers,
    )
