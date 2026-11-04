"""CSV validation for uploads and for the raw UCI files.

Guarantees:
  * ``validate_csv_bytes`` raises ONLY ``CsvValidationError`` for bad input
    (status 400 = unreadable, 413 = too large, 422 = readable but unusable).
  * The returned frame has exactly the 11 MEASUREMENT_COLUMNS as float64, in
    canonical order, with NaN for missing/non-numeric cells. Row order is the
    file order; the index is 0..n-1.
  * Anything suspicious that does not make the file unusable becomes a warning
    string (extra columns, non-numeric cells, duplicates, out-of-range values).
"""
from __future__ import annotations

import io
import math
import re
from pathlib import PurePosixPath, PureWindowsPath

import numpy as np
import pandas as pd

from app.schemas import MEASUREMENT_KEYS

MEASUREMENT_COLUMNS: list[str] = list(MEASUREMENT_KEYS)

# Plausible physical ranges (as published in the UCI description, widened slightly).
# Values outside are WARNINGS, never errors: real plants and uploads may differ.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "AT": (-10.0, 45.0),
    "AP": (980.0, 1040.0),
    "AH": (20.0, 101.0),
    "AFDP": (1.0, 8.0),
    "GTEP": (15.0, 45.0),
    "TIT": (1000.0, 1110.0),
    "TAT": (500.0, 560.0),
    "TEY": (100.0, 190.0),
    "CDP": (9.0, 16.0),
    "CO": (0.0, 50.0),
    "NOX": (20.0, 130.0),
}

MAX_BAD_CELL_FRACTION = 0.20  # more than this share of non-numeric cells -> 422
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_FORMULA_PREFIXES = ("=", "@")  # spreadsheet formula injection markers; never numeric


class CsvValidationError(ValueError):
    """Raised for any user-input problem. ``status_code`` is the HTTP status the API should use."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def infer_year_from_filename(filename: str) -> int | None:
    """Return the first plausible 4-digit year (1900-2099) found in the basename, else None.

    ``gt_2014.csv`` -> 2014, ``gt_2014_sample300.csv`` -> 2014, ``plant.csv`` -> None.
    """
    base = safe_basename(filename, strict=False)
    match = _YEAR_RE.search(base)
    return int(match.group(1)) if match else None


def safe_basename(filename: str, strict: bool = True) -> str:
    """Return the basename of ``filename``.

    With ``strict=True`` (used for uploads) any directory component, ``..`` segment,
    NUL byte or empty name raises ``CsvValidationError(400)``: a client has no business
    sending a path, only a file name.
    """
    name = (filename or "").strip()
    if strict:
        if not name or "\x00" in name:
            raise CsvValidationError("filename is empty or contains invalid characters", 400)
        if "/" in name or "\\" in name or name in {".", ".."} or ".." in name.split("."):
            raise CsvValidationError(
                "filename must be a plain file name without directory components", 400
            )
        return name
    # non-strict: best effort basename for year inference
    name = PureWindowsPath(name).name
    return PurePosixPath(name).name


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvValidationError(
            f"file is not valid UTF-8 text (byte offset {exc.start}); please upload a UTF-8 CSV", 400
        ) from exc


def _read_raw_table(text: str) -> pd.DataFrame:
    """Parse CSV text into an all-string frame (no numeric coercion yet)."""
    kwargs = dict(dtype=str, keep_default_na=False, skipinitialspace=True, skip_blank_lines=True)
    try:
        frame = pd.read_csv(io.StringIO(text), **kwargs)
        if frame.shape[1] == 1 and ";" in str(frame.columns[0]):
            frame = pd.read_csv(io.StringIO(text), sep=";", **kwargs)
    except pd.errors.EmptyDataError as exc:
        raise CsvValidationError("file is empty (no header row)", 422) from exc
    except pd.errors.ParserError as exc:
        raise CsvValidationError(f"malformed CSV: {str(exc).splitlines()[0][:200]}", 422) from exc
    except Exception as exc:  # noqa: BLE001 - never leak arbitrary exceptions for user input
        raise CsvValidationError(f"could not parse CSV: {type(exc).__name__}", 422) from exc
    return frame


def _coerce_numeric(series: pd.Series) -> tuple[pd.Series, int, int]:
    """Convert a string column to float64.

    Returns (values, n_missing, n_bad): empty cells are missing (NaN, not an error);
    non-empty cells that do not parse as finite numbers (including spreadsheet
    formulas like ``=1+1``) become NaN and are counted as bad.
    """
    # Fast path: a plain vectorised parse handles the overwhelmingly common case of
    # well-formed numeric cells. Only the cells that did NOT parse to a finite number
    # go through the per-cell string logic below (empty/NaN-words/formula detection),
    # which is ~20x slower. Cells that parse as finite numbers can never start with a
    # formula prefix, so the result is identical to running the slow path on every cell.
    fast = pd.to_numeric(series, errors="coerce").astype("float64")
    fast_ok = np.isfinite(fast.to_numpy(dtype="float64"))
    if fast_ok.all():
        return fast, 0, 0
    pending = series[~fast_ok]

    stripped = pending.astype(str).str.strip()
    is_empty = stripped.eq("") | stripped.str.lower().isin({"nan", "na", "null", "none"})
    is_formula = stripped.str.startswith(_FORMULA_PREFIXES)
    candidate = stripped.where(~is_formula, other="__formula__")
    numeric = pd.to_numeric(candidate, errors="coerce").astype("float64")
    numeric = numeric.where(np.isfinite(numeric), other=np.nan)
    is_bad = numeric.isna() & ~is_empty

    out = fast.copy()
    out[~fast_ok] = numeric.to_numpy(dtype="float64")
    return out, int(is_empty.sum()), int(is_bad.sum())


def validate_csv_bytes(filename: str, data: bytes, max_bytes: int) -> tuple[pd.DataFrame, list[str]]:
    """Validate raw CSV bytes and return ``(frame, warnings)``.

    ``frame`` has exactly MEASUREMENT_COLUMNS (float64, canonical order, index 0..n-1).
    Raises ``CsvValidationError`` with status 400 (bad name / not UTF-8), 413 (too large)
    or 422 (missing columns, empty, malformed, too many non-numeric cells).
    """
    warnings: list[str] = []
    name = safe_basename(filename, strict=True)

    if data is None or len(data) == 0:
        raise CsvValidationError(f"{name}: file is empty", 422)
    if len(data) > max_bytes:
        raise CsvValidationError(
            f"{name}: file is {len(data):,} bytes, larger than the {max_bytes:,} byte limit", 413
        )

    text = _decode(data)
    if not text.strip():
        raise CsvValidationError(f"{name}: file is empty", 422)

    raw = _read_raw_table(text)

    # --- header mapping (whitespace + case tolerant) -------------------------------
    canonical_by_upper = {c.upper(): c for c in MEASUREMENT_COLUMNS}
    mapping: dict[str, str] = {}
    extra: list[str] = []
    for col in raw.columns:
        key = str(col).strip().upper()
        if key in canonical_by_upper and canonical_by_upper[key] not in mapping.values():
            mapping[str(col)] = canonical_by_upper[key]
        else:
            extra.append(str(col).strip())
    missing = [c for c in MEASUREMENT_COLUMNS if c not in mapping.values()]
    if missing:
        raise CsvValidationError(
            f"{name}: missing required column(s): {', '.join(missing)}. "
            f"Expected header: {','.join(MEASUREMENT_COLUMNS)}",
            422,
        )
    if extra:
        warnings.append(f"{name}: ignored {len(extra)} extra column(s): {', '.join(extra[:10])}")

    raw = raw.rename(columns=mapping)[MEASUREMENT_COLUMNS]
    if len(raw) == 0:
        raise CsvValidationError(f"{name}: header only, no data rows", 422)

    # --- numeric coercion -----------------------------------------------------------
    out = pd.DataFrame(index=range(len(raw)))
    total_bad = 0
    bad_by_col: dict[str, int] = {}
    missing_by_col: dict[str, int] = {}
    for col in MEASUREMENT_COLUMNS:
        values, n_missing, n_bad = _coerce_numeric(raw[col])
        out[col] = values.to_numpy(dtype="float64")
        if n_bad:
            bad_by_col[col] = n_bad
        if n_missing:
            missing_by_col[col] = n_missing
        total_bad += n_bad
    total_cells = len(raw) * len(MEASUREMENT_COLUMNS)
    if total_bad:
        detail = ", ".join(f"{c}={n}" for c, n in bad_by_col.items())
        frac = total_bad / total_cells
        if frac > MAX_BAD_CELL_FRACTION:
            raise CsvValidationError(
                f"{name}: {total_bad} of {total_cells} cells ({frac:.0%}) are non-numeric ({detail}); "
                f"more than {MAX_BAD_CELL_FRACTION:.0%} is not usable",
                422,
            )
        warnings.append(
            f"{name}: {total_bad} non-numeric cell(s) replaced with missing values ({detail})"
        )
    if missing_by_col:
        detail = ", ".join(f"{c}={n}" for c, n in missing_by_col.items())
        warnings.append(f"{name}: empty cell(s) treated as missing ({detail})")

    if out.isna().all(axis=1).any():
        n_blank = int(out.isna().all(axis=1).sum())
        warnings.append(f"{name}: {n_blank} row(s) have no numeric values at all")

    # --- duplicates -------------------------------------------------------------------
    n_dup = int(out.duplicated().sum())
    if n_dup:
        warnings.append(
            f"{name}: {n_dup} exact duplicate row(s) found (kept; hourly aggregates can legitimately repeat)"
        )

    # --- plausibility ranges (warnings only) ----------------------------------------
    for col, (lo, hi) in PLAUSIBLE_RANGES.items():
        series = out[col]
        n_out = int(((series < lo) | (series > hi)).sum())
        if n_out:
            warnings.append(
                f"{name}: {col} has {n_out} value(s) outside the plausible range [{lo:g}, {hi:g}] "
                f"(observed min {series.min():.4g}, max {series.max():.4g}); kept as-is"
            )

    out = out.reset_index(drop=True)
    out.columns = list(MEASUREMENT_COLUMNS)
    return out, warnings


def is_finite_number(value: object) -> bool:
    """Small helper used by callers that need to serialise floats as JSON (NaN -> None)."""
    try:
        return math.isfinite(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
