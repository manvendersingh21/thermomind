"""Test configuration for the API tests.

The API tests run against temporary data/model/db locations built from the
300-row fixture (copied as gt_2011..gt_2015.csv because ``load_uci_dir`` needs
all five files). The paths are patched on ``app.config`` for the duration of
``test_api.py`` only (module scope) and restored afterwards, so sibling test
modules that rely on the real ``config.RAW_UCI_DIR`` / ``config.MODEL_DIR`` are
unaffected. ``app.services`` reads ``config.*`` lazily, which makes this safe.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from app import config, services

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "data" / "fixtures" / "gt_2014_sample300.csv"
UCI_YEARS = (2011, 2012, 2013, 2014, 2015)
_PATCHED = ("DATA_DIR", "RAW_UCI_DIR", "FIXTURE_DIR", "MODEL_DIR", "DB_PATH")


@pytest.fixture(scope="session")
def fixture_csv_path() -> Path:
    return FIXTURE


@pytest.fixture(scope="session")
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def tmp_env():
    """Temporary data dir (fixture-based raw UCI files), model dir and sqlite db."""
    tmp = Path(tempfile.mkdtemp(prefix="thermomind_test_"))
    data_dir = tmp / "data"
    raw_dir = data_dir / "raw" / "uci_551"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for year in UCI_YEARS:
        shutil.copyfile(FIXTURE, raw_dir / f"gt_{year}.csv")
    (data_dir / "fixtures").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, data_dir / "fixtures" / FIXTURE.name)
    (data_dir / "models").mkdir(parents=True, exist_ok=True)

    saved = {name: getattr(config, name) for name in _PATCHED}
    config.DATA_DIR = data_dir
    config.RAW_UCI_DIR = raw_dir
    config.FIXTURE_DIR = data_dir / "fixtures"
    config.MODEL_DIR = data_dir / "models"
    config.DB_PATH = data_dir / "thermomind_test.db"
    services.reset()
    try:
        yield data_dir
    finally:
        for name, value in saved.items():
            setattr(config, name, value)
        services.reset()
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def trained_model(tmp_env):
    """Train the baseline on the seeded fixture (fast, 1500 rows) when analytics is available."""
    services.seed_uci_if_available()
    try:
        from app.analytics.train import train_baseline
    except Exception:  # noqa: BLE001
        return None
    bundle = services.get_repo().get(services.UCI_DATASET_ID)
    train_baseline(bundle.frame, Path(config.MODEL_DIR), seed=42)
    return services.reload_model()


@pytest.fixture(scope="module")
def client(trained_model):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
