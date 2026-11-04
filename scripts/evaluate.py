#!/usr/bin/env python
"""Evaluate the deterministic analytics on the four scenarios plus three real "normal" windows.

Usage (repo root, venv active): python scripts/evaluate.py [--model-dir data/models] [--raw-dir data/raw/uci_551]
Prints a markdown table with REAL numbers from this run and writes docs/EVALUATION_RESULTS.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app import config  # noqa: E402
from app.analytics.baseline import BaselineModel  # noqa: E402
from app.analytics.evidence import NOTABLE_FLAG, analyze_case, top_hypothesis  # noqa: E402
from app.analytics.scenarios import SCENARIOS, apply_scenario  # noqa: E402
from app.schemas import SampleRange  # noqa: E402

NORMAL_WINDOWS = [(2015, 500, 620), (2015, 3000, 3120), (2015, 6000, 6120)]


def load_frame(raw_dir: Path):
    try:
        from app.data.uci_loader import load_uci_dir

        return load_uci_dir(raw_dir).frame
    except Exception:
        from app.analytics._io import load_raw_frame

        return load_raw_frame(raw_dir)


def year_frame(frame, year: int):
    return frame[frame["source_year"] == year].sort_values("row_index", kind="stable").reset_index(drop=True)


def run_case(frame, model, scenario_id: str, year: int, start: int, end: int, seed: int) -> dict:
    yf = year_frame(frame, year)
    ref_start = max(0, start - config.DEFAULT_REFERENCE_ROWS)
    window_df = yf.iloc[start:end]
    reference_df = yf.iloc[ref_start:start]
    result = apply_scenario(window_df, scenario_id, seed=seed)
    case_id = f"eval_{scenario_id}_{year}_{start}_{end}"
    analysis = analyze_case(
        case_id, result.frame, reference_df, result, model,
        SampleRange(source_year=year, start=start, end=end),
        SampleRange(source_year=year, start=ref_start, end=start),
    )
    notable = [e.evidence_id for e in analysis.evidence if NOTABLE_FLAG in e.flags]
    resid = analysis.evidence_by_id().get("ev_tey_residual_01")
    resid2 = analysis.evidence_by_id().get("ev_tey_residual_02")
    top = top_hypothesis(analysis.hypothesis_evals)
    return {
        "case_id": case_id,
        "scenario_id": scenario_id,
        "synthetic": result.synthetic,
        "window": {"source_year": year, "start": start, "end": end},
        "reference": {"source_year": year, "start": ref_start, "end": start},
        "top_hypothesis": top,
        "scores": {k: v.deterministic_support_score for k, v in analysis.hypothesis_evals.items()},
        "notable_evidence_ids": notable,
        "residual_notable": bool(resid is not None and NOTABLE_FLAG in resid.flags) or bool(resid2 is not None and NOTABLE_FLAG in resid2.flags),
        "residual_mean": analysis.baseline.residual_mean if analysis.baseline else None,
        "residual_z_raw": analysis.baseline.residual_z if analysis.baseline else None,
        "residual_z_vs_reference": resid.values.get("z_vs_reference") if resid is not None else None,
        "reference_residual_mean": analysis.baseline.reference_residual_mean if analysis.baseline else None,
        "evidence_z": {e.evidence_id: e.z_score for e in analysis.evidence},
        "sensor_consistency_flags": analysis.data_quality.sensor_consistency_flags,
        "out_of_training_range": analysis.data_quality.out_of_training_range,
        "evidence_count": len(analysis.evidence),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_UCI_DIR)
    parser.add_argument("--model-dir", type=Path, default=config.MODEL_DIR)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "EVALUATION_RESULTS.json")
    args = parser.parse_args()

    frame = load_frame(args.raw_dir)
    model = BaselineModel.load(args.model_dir)
    ev = model.evaluation

    cases = []
    for sid, info in SCENARIOS.items():
        cases.append(run_case(frame, model, sid, info.default_year, info.default_start, info.default_end, info.default_seed))
    for year, start, end in NORMAL_WINDOWS:
        cases.append(run_case(frame, model, "S01_NORMAL", year, start, end, SCENARIOS["S01_NORMAL"].default_seed))

    normal_cases = [c for c in cases if c["scenario_id"] == "S01_NORMAL"]
    false_positives = sum(1 for c in normal_cases if c["residual_notable"])

    print(f"## Baseline model {ev.model_id} / {ev.model_version} ({ev.algorithm})\n")
    print("| split | rows | MAE (MWh) | RMSE (MWh) | R2 |")
    print("|---|---|---|---|---|")
    print(f"| validation {ev.split.validation_years} | {ev.validation.n} | {ev.validation.mae:.3f} | {ev.validation.rmse:.3f} | {ev.validation.r2:.4f} |")
    print(f"| holdout {ev.split.test_years} | {ev.holdout.n} | {ev.holdout.mae:.3f} | {ev.holdout.rmse:.3f} | {ev.holdout.r2:.4f} |")
    for name, m in ev.naive_baselines.items():
        print(f"| naive {name} (holdout) | {m.n} | {m.mae:.3f} | {m.rmse:.3f} | {m.r2:.4f} |")
    print(f"\nresidual_std_validation = {ev.residual_std_validation:.3f} MWh; residual quantiles = "
          + ", ".join(f"{k}={v:.2f}" for k, v in ev.residual_quantiles_validation.items()) + "\n")

    print("## Scenario evaluation (deterministic rules; heuristic scores, not diagnoses)\n")
    print("| case | window | synthetic | top deterministic hypothesis | scores | notable evidence ids | residual notable? |")
    print("|---|---|---|---|---|---|---|")
    for c in cases:
        w = c["window"]
        scores = ", ".join(f"{k.split('_')[0]}={v:.2f}" for k, v in c["scores"].items())
        print(f"| {c['scenario_id']} | {w['source_year']} [{w['start']},{w['end']}) | {c['synthetic']} | {c['top_hypothesis']} | {scores} | "
              f"{', '.join(c['notable_evidence_ids']) or '-'} | {'YES' if c['residual_notable'] else 'no'} |")
    print(f"\nNormal (real-only) windows with a notable residual flag (false positives): {false_positives} of {len(normal_cases)}\n")

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "model": ev.model_dump(),
        "notable_threshold_z": 2.0,
        "cases": cases,
        "normal_window_false_positive_count": false_positives,
        "normal_window_count": len(normal_cases),
        "note": "Deterministic heuristic evaluation on UCI 551 data; synthetic overlays are illustrations, not recorded faults. Real numbers from this run.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
