#!/usr/bin/env python
"""Seed the demo: load the UCI dataset, train the baseline if missing, and run one
offline (use_meta=False) S02 investigation through the same service functions the
API uses. Prints the case id. Import-based, no HTTP server needed.

Usage: .venv/bin/python scripts/seed_demo.py  (or `make seed`)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("seed_demo")


def main() -> int:
    from app import config, services
    from app.schemas import InvestigationRequest

    if not services.uci_raw_files_present():
        log.error("UCI raw files not found in %s. Run `make data` (scripts/fetch_uci.py) first.", config.RAW_UCI_DIR)
        return 2
    if not services.seed_uci_if_available():
        log.error("dataset seeding failed")
        return 2
    bundle = services.get_repo().get(services.UCI_DATASET_ID)
    log.info("dataset %s: %d rows, years %s", bundle.dataset_id, len(bundle.frame), bundle.years())

    model = services.get_model(recheck=True)
    if model is None:
        from app.analytics.train import train_baseline

        log.info("baseline model missing; training into %s ...", config.MODEL_DIR)
        evaluation = train_baseline(bundle.frame, Path(config.MODEL_DIR), seed=42)
        log.info("trained %s: holdout MAE %.3f MWh, R2 %.3f", evaluation.model_version, evaluation.holdout.mae, evaluation.holdout.r2)
        model = services.reload_model()
    else:
        log.info("baseline model %s already present (holdout MAE %.3f MWh)", model.version, model.evaluation.holdout.mae)

    req = InvestigationRequest(
        dataset_id=services.UCI_DATASET_ID,
        scenario_id="S02_INTAKE_RESTRICTION",
        year=2014,
        start_index=1200,
        end_index=1320,
        seed=42,
        use_meta=False,
    )
    inv = services.run_investigation_pipeline(req)
    log.info(
        "investigation %s: status=%s mode=%s meta_used=%s evidence=%d report=%s",
        inv.case_id, inv.status, inv.mode, inv.meta_used, len(inv.evidence),
        inv.report.report_status if inv.report else None,
    )
    if inv.status == "failed":
        log.error("investigation failed: %s", inv.error)
        return 1
    print(inv.case_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
