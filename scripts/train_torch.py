#!/usr/bin/env python
"""Train the ThermoMind challenger MLP (torch, GPU if available) on the raw UCI csv files.

Usage (from repo root, venv active, torch installed via apps/api/requirements-gpu.txt):
    python scripts/train_torch.py [--raw-dir data/raw/uci_551] [--model-dir data/models] [--seed 42]
                                  [--epochs 300] [--device cuda:0|cpu] [--verbose]
Writes model_dir/mlp_v1.pt + mlp_v1.json, prints the ModelEvaluation JSON (real metrics from this run)
and the production-vs-challenger comparison table on exactly the same chronological split.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app import config  # noqa: E402
from app.analytics.comparison import comparison_table, gpu_info, load_model_comparison  # noqa: E402
from app.analytics.torch_baseline import DEFAULT_EPOCHS, train_torch_baseline  # noqa: E402


def load_frame(raw_dir: Path):
    try:
        from app.data.uci_loader import load_uci_dir

        return load_uci_dir(raw_dir).frame, "app.data.uci_loader.load_uci_dir"
    except Exception as exc:  # noqa: BLE001 - loader unavailable: fall back, never block
        from app.analytics._io import load_raw_frame

        print(f"[train_torch] app.data loader unavailable ({type(exc).__name__}: {exc}); using app.analytics._io",
              file=sys.stderr)
        return load_raw_frame(raw_dir), "app.analytics._io.load_raw_frame"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_UCI_DIR)
    parser.add_argument("--model-dir", type=Path, default=config.MODEL_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--device", type=str, default=None, help="torch device (default: cuda:0 if available)")
    parser.add_argument("--verbose", action="store_true", help="print per-epoch validation MAE")
    args = parser.parse_args()

    print(f"[train_torch] gpu: {gpu_info()}", file=sys.stderr)
    frame, loader = load_frame(args.raw_dir)
    print(f"[train_torch] loaded {len(frame)} rows via {loader}; "
          f"years={sorted(frame['source_year'].unique().tolist())}", file=sys.stderr)

    evaluation = train_torch_baseline(frame, args.model_dir, seed=args.seed, epochs=args.epochs,
                                      device=args.device, verbose=args.verbose)
    print(f"[train_torch] done: device={evaluation.device} training_seconds={evaluation.training_seconds:.2f} "
          f"-> {args.model_dir}", file=sys.stderr)
    print(json.dumps(evaluation.model_dump(), indent=2))

    try:
        comparison = load_model_comparison(args.model_dir)
    except FileNotFoundError as exc:
        print(f"[train_torch] no production baseline to compare against ({exc}); run scripts/train.py first",
              file=sys.stderr)
        return 0
    print("\n[train_torch] production vs challenger (identical chronological split):", file=sys.stderr)
    print(comparison_table(comparison), file=sys.stderr)
    print(f"[train_torch] selection rule: {comparison.selection_rule}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
