"""Private, dependency-free loader for the raw UCI csv files.

The canonical loader is ``app.data.uci_loader.load_uci_dir`` (owned by the Data
agent). This module exists so analytics scripts and tests are never blocked on
that module: it produces a frame in the same contract format
(``source_year``, ``row_index`` and the 11 float64 measurement columns).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.schemas import MEASUREMENT_KEYS

_YEAR_RE = re.compile(r"gt_(\d{4})\.csv$")


def load_year_csv(path: Path, source_year: int) -> pd.DataFrame:
    """Read one gt_YYYY.csv and return the contract frame for that year."""
    raw = pd.read_csv(path)
    missing = [c for c in MEASUREMENT_KEYS if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    out = pd.DataFrame({"source_year": int(source_year), "row_index": range(len(raw))})
    for col in MEASUREMENT_KEYS:
        out[col] = pd.to_numeric(raw[col], errors="coerce").astype("float64")
    out["source_year"] = out["source_year"].astype("int64")
    out["row_index"] = out["row_index"].astype("int64")
    return out


def load_raw_frame(raw_dir: Path) -> pd.DataFrame:
    """Read every gt_YYYY.csv in ``raw_dir`` (sorted by year) into one contract frame."""
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("gt_*.csv"))
    frames = []
    for path in files:
        m = _YEAR_RE.search(path.name)
        if not m:
            continue
        frames.append(load_year_csv(path, int(m.group(1))))
    if not frames:
        raise FileNotFoundError(f"no gt_YYYY.csv files found in {raw_dir}")
    return pd.concat(frames, ignore_index=True)


def load_fixture_frame(path: Path, source_year: int = 2014) -> pd.DataFrame:
    """Load the redistributable 300-row fixture as a contract frame."""
    return load_year_csv(Path(path), source_year)
