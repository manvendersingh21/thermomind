#!/usr/bin/env python
"""Train the ThermoMind baseline TEY model from the raw UCI csv files.

Usage (from repo root, venv active):
    python scripts/train.py [--raw-dir data/raw/uci_551] [--model-dir data/models] [--seed 42]
Prints the ModelEvaluation JSON (real metrics from this run) to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app import config  # noqa: E402
from app.analytics.train import train_baseline  # noqa: E402


def load_frame(raw_dir: Path):
    try:
        from app.data.uci_loader import load_uci_dir  # provided by the Data agent

        bundle = load_uci_dir(raw_dir)
        return bundle.frame, "app.data.uci_loader.load_uci_dir"
    except Exception as exc:  # ImportError or a not-yet-finished loader: fall back, never block
        from app.analytics._io import load_raw_frame

        print(f"[train] app.data loader unavailable ({type(exc).__name__}: {exc}); using app.analytics._io",
              file=sys.stderr)
        return load_raw_frame(raw_dir), "app.analytics._io.load_raw_frame"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_UCI_DIR)
    parser.add_argument("--model-dir", type=Path, default=config.MODEL_DIR)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    t0 = time.time()
    frame, loader = load_frame(args.raw_dir)
    print(f"[train] loaded {len(frame)} rows via {loader}; years={sorted(frame['source_year'].unique().tolist())}",
          file=sys.stderr)
    evaluation = train_baseline(frame, args.model_dir, seed=args.seed)
    print(f"[train] done in {time.time() - t0:.1f}s -> {args.model_dir}", file=sys.stderr)
    print(json.dumps(evaluation.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
