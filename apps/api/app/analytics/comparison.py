"""Production-vs-challenger model comparison (``load_model_comparison``) and GPU probing (``gpu_info``).

torch is optional: ``gpu_info`` falls back to ``nvidia-smi`` and then to ``{"available": False}``;
``load_model_comparison`` only reads the JSON evaluations written by ``train.py`` / ``torch_baseline.py``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.schemas import ModelComparison, ModelEvaluation

PRODUCTION_JSON = "baseline_v1.json"
CHALLENGER_JSONS = ("mlp_v1.json",)  # known challenger artefacts; any other *.json with role=="challenger" is also picked up

SELECTION_RULE = (
    "Production baseline is the deterministic HGBR; the challenger is reported for benchmarking on the identical "
    "chronological split. Selection would be made on 2014 validation MAE only, never on the 2015 holdout."
)


def gpu_info() -> dict[str, Any]:
    """``{"available", "name", "memory_mb", "driver", "backend"}`` via torch if importable, else nvidia-smi, else unavailable.

    ``backend`` says which probe answered ("torch" means CUDA is usable from this process; "nvidia-smi" means a GPU is
    present on the host but torch is not installed/CUDA-enabled here)."""
    info: dict[str, Any] = {"available": False, "name": None, "memory_mb": None, "driver": None, "backend": None}
    try:
        import torch  # noqa: WPS433

        info["driver"] = f"torch {torch.__version__}" + (f" cuda {torch.version.cuda}" if torch.version.cuda else "")
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            info.update(available=True, name=str(props.name), memory_mb=int(props.total_memory // (1024 * 1024)),
                        backend="torch")
            return info
    except Exception:  # noqa: BLE001 - torch missing or broken: fall through to nvidia-smi
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            line = (out.stdout or "").strip().splitlines()
            if out.returncode == 0 and line:
                parts = [p.strip() for p in line[0].split(",")]
                name = parts[0] if parts else None
                mem = None
                if len(parts) > 1:
                    digits = "".join(ch for ch in parts[1] if ch.isdigit())
                    mem = int(digits) if digits else None
                driver = parts[2] if len(parts) > 2 else None
                # torch absent (or without CUDA): the GPU exists on the host; report it via nvidia-smi.
                info.update(available=True, name=name, memory_mb=mem, backend="nvidia-smi",
                            driver=((info["driver"] or "") + (f" nvidia-driver {driver}" if driver else "")).strip() or None)
        except Exception:  # noqa: BLE001
            pass
    return info


def _read_evaluation(path: Path) -> ModelEvaluation | None:
    try:
        return ModelEvaluation.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - unreadable/foreign json is ignored, never crashes the endpoint
        return None


def load_challengers(model_dir: Path) -> list[ModelEvaluation]:
    """All challenger evaluations present in ``model_dir`` (empty list when none)."""
    model_dir = Path(model_dir)
    if not model_dir.exists():
        return []
    found: list[ModelEvaluation] = []
    seen: set[str] = set()
    for path in sorted(model_dir.glob("*.json")):
        if path.name == PRODUCTION_JSON:
            continue
        ev = _read_evaluation(path)
        if ev is None or ev.role != "challenger":
            continue
        key = f"{ev.model_id}:{ev.model_version}"
        if key in seen:
            continue
        seen.add(key)
        found.append(ev)
    return found


def load_model_comparison(model_dir: Path) -> ModelComparison:
    """Read the production evaluation (``baseline_v1.json``) and any challengers from ``model_dir``.

    Raises ``FileNotFoundError`` when the production model has not been trained (API maps this to 404).
    A missing challenger is not an error: ``challengers == []``.
    """
    model_dir = Path(model_dir)
    prod_path = model_dir / PRODUCTION_JSON
    if not prod_path.exists():
        raise FileNotFoundError(f"production model evaluation not found: {prod_path}")
    production = _read_evaluation(prod_path)
    if production is None:
        raise FileNotFoundError(f"production model evaluation unreadable: {prod_path}")
    return ModelComparison(
        production=production,
        challengers=load_challengers(model_dir),
        selection_rule=SELECTION_RULE,
        gpu=gpu_info(),
    )


def comparison_table(comparison: ModelComparison) -> str:
    """Plain-text table (production vs challengers, validation + holdout) for scripts/CLI output."""
    rows = [comparison.production, *comparison.challengers]
    header = f"{'model':<24}{'role':<20}{'split':<12}{'MAE':>9}{'RMSE':>9}{'R2':>9}{'n':>7}  device / train s"
    lines = [header, "-" * len(header)]
    for ev in rows:
        for split_name, ms in (("validation", ev.validation), ("holdout", ev.holdout)):
            extra = ""
            if split_name == "validation":
                secs = f"{ev.training_seconds:.1f}s" if ev.training_seconds is not None else "n/a"
                extra = f"{ev.device or 'n/a'} / {secs}"
            lines.append(
                f"{ev.model_version:<24}{ev.role:<20}{split_name:<12}{ms.mae:>9.4f}{ms.rmse:>9.4f}{ms.r2:>9.4f}{ms.n:>7}  {extra}"
            )
    return "\n".join(lines)
