"""``BaselineModel``: load the trained baseline and produce expected TEY / residuals / OOD counts."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.analytics.train import JOBLIB_NAME, JSON_NAME
from app.schemas import FEATURE_KEYS, TARGET_KEY, ModelEvaluation


class BaselineModel:
    def __init__(self, model, features: list[str], evaluation: ModelEvaluation):
        self._model = model
        self.features = list(features)
        self.evaluation = evaluation
        self.version: str = evaluation.model_version

    @classmethod
    def load(cls, model_dir: Path) -> "BaselineModel":
        model_dir = Path(model_dir)
        joblib_path = model_dir / JOBLIB_NAME
        json_path = model_dir / JSON_NAME
        if not joblib_path.exists() or not json_path.exists():
            raise FileNotFoundError(f"baseline model not found in {model_dir} (expected {JOBLIB_NAME} and {JSON_NAME})")
        bundle = joblib.load(joblib_path)
        evaluation = ModelEvaluation.model_validate_json(json_path.read_text(encoding="utf-8"))
        features = list(bundle.get("features", FEATURE_KEYS))
        return cls(bundle["model"], features, evaluation)

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.features if c not in frame.columns]
        if missing:
            raise ValueError(f"frame is missing feature columns: {missing}")
        return frame[self.features].to_numpy(dtype=float)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Expected TEY (MWh) per row given the FEATURE_KEYS readings. NaN features yield NaN predictions."""
        if len(frame) == 0:
            return np.array([], dtype=float)
        X = self._matrix(frame)
        bad = np.isnan(X).any(axis=1)
        out = np.full(len(X), np.nan, dtype=float)
        if (~bad).any():
            out[~bad] = self._model.predict(X[~bad])
        return out

    def residuals(self, frame: pd.DataFrame) -> np.ndarray:
        """observed TEY - expected TEY, per row."""
        observed = frame[TARGET_KEY].to_numpy(dtype=float)
        return observed - self.predict(frame)

    def out_of_range_counts(self, frame: pd.DataFrame) -> dict[str, int]:
        """Rows per feature whose value lies outside the training min/max (``feature_ranges_train``)."""
        counts: dict[str, int] = {}
        for key, (lo, hi) in self.evaluation.feature_ranges_train.items():
            if key not in frame.columns:
                continue
            vals = frame[key].to_numpy(dtype=float)
            counts[key] = int(np.sum((vals < lo) | (vals > hi)))
        return counts
