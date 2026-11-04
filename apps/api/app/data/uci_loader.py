"""Loaders that turn CSV files into a ``DatasetBundle``.

Frame contract (see contracts/api.md):
  columns = ["source_year", "row_index"] + MEASUREMENT_COLUMNS
  * source_year : int. The calendar year the file covers. For uploads whose
    filename carries no year the value is UNKNOWN_YEAR (-1); it is excluded from
    ``years`` lists and surfaced as the warning "source year unknown".
  * row_index   : int, 0-based position within the year, in file order. This is
    the only time axis; no timestamps exist and none are fabricated.
  * measurements: float64, NaN for missing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.data.provenance import sha256_bytes
from app.data.validator import (
    MEASUREMENT_COLUMNS,
    CsvValidationError,
    infer_year_from_filename,
    validate_csv_bytes,
)
from app.schemas import UCI_SOURCE_ID, SourceFileInfo

__all__ = [
    "MEASUREMENT_COLUMNS",
    "UCI_YEARS",
    "UCI_DATASET_ID",
    "UNKNOWN_YEAR",
    "load_uci_dir",
    "load_csv_files",
    "infer_year_from_filename",
]

UCI_YEARS: list[int] = [2011, 2012, 2013, 2014, 2015]
UCI_DATASET_ID = "ds_uci_551"
UNKNOWN_YEAR = -1
# The raw UCI files are ~0.6 MB each; allow generous headroom but still bound memory.
_RAW_FILE_MAX_BYTES = 256 * 1024 * 1024
FRAME_COLUMNS = ["source_year", "row_index"] + MEASUREMENT_COLUMNS


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _year_block(frame: pd.DataFrame, year: int, row_offset: int = 0) -> pd.DataFrame:
    """Prefix a validated measurement frame with source_year and row_index."""
    block = pd.DataFrame(
        {
            "source_year": pd.Series([year] * len(frame), dtype="int64"),
            "row_index": pd.Series(range(row_offset, row_offset + len(frame)), dtype="int64"),
        }
    )
    for col in MEASUREMENT_COLUMNS:
        block[col] = frame[col].to_numpy(dtype="float64")
    return block


def _empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="float64") for c in MEASUREMENT_COLUMNS})
    frame.insert(0, "row_index", pd.Series(dtype="int64"))
    frame.insert(0, "source_year", pd.Series(dtype="int64"))
    return frame


def _assemble(blocks: list[pd.DataFrame]) -> pd.DataFrame:
    if not blocks:
        return _empty_frame()
    frame = pd.concat(blocks, ignore_index=True)
    frame["source_year"] = frame["source_year"].astype("int64")
    frame["row_index"] = frame["row_index"].astype("int64")
    for col in MEASUREMENT_COLUMNS:
        frame[col] = frame[col].astype("float64")
    return frame[FRAME_COLUMNS]


def load_uci_dir(raw_dir: Path) -> "DatasetBundle":
    """Read gt_2011.csv ... gt_2015.csv from ``raw_dir`` in year order.

    Raises FileNotFoundError when the directory or any of the five files is missing
    (run ``scripts/fetch_uci.py``). Raises CsvValidationError if a file is corrupt.
    """
    from app.data.repository import DatasetBundle  # local import avoids a circular import

    raw_dir = Path(raw_dir)
    expected = {year: raw_dir / f"gt_{year}.csv" for year in UCI_YEARS}
    missing = [p.name for p in expected.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            f"UCI raw files missing in {raw_dir}: {', '.join(missing)} "
            "(run `python scripts/fetch_uci.py` or `make data`)"
        )

    blocks: list[pd.DataFrame] = []
    source_files: list[SourceFileInfo] = []
    warnings: list[str] = []
    for year in UCI_YEARS:
        path = expected[year]
        data = path.read_bytes()
        frame, file_warnings = validate_csv_bytes(path.name, data, _RAW_FILE_MAX_BYTES)
        warnings.extend(file_warnings)
        blocks.append(_year_block(frame, year))
        source_files.append(
            SourceFileInfo(
                filename=path.name,
                source_year=year,
                rows=len(frame),
                sha256=sha256_bytes(data),
                bytes=len(data),
            )
        )

    return DatasetBundle(
        dataset_id=UCI_DATASET_ID,
        frame=_assemble(blocks),
        source=UCI_SOURCE_ID,
        source_files=source_files,
        warnings=warnings,
        created_at_utc=_now_utc(),
    )


def load_csv_files(files: list[tuple[str, bytes]], source: str = "USER_UPLOAD") -> "DatasetBundle":
    """Build a bundle from uploaded ``(filename, bytes)`` pairs.

    * Each file is validated with ``validate_csv_bytes`` (raises CsvValidationError).
    * ``source_year`` is inferred from the filename (``*2014*``). Files with no
      recognisable year get ``source_year = -1`` plus the warning "source year unknown".
    * Files are grouped by year and ordered by ascending year (unknown last). Several
      files for the same year are concatenated in the order given; row_index continues
      across them so it stays unique within the year.
    * dataset_id is derived from the content hashes, so re-uploading identical files
      yields the same id.
    """
    from app import config
    from app.data.repository import DatasetBundle  # local import avoids a circular import

    if not files:
        raise CsvValidationError("no files provided", 422)

    max_bytes = int(getattr(config, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
    validated: list[tuple[int | None, str, pd.DataFrame, str, int]] = []
    warnings: list[str] = []
    for filename, data in files:
        frame, file_warnings = validate_csv_bytes(filename, data, max_bytes)
        warnings.extend(file_warnings)
        year = infer_year_from_filename(filename)
        if year is None:
            warnings.append(f"{filename}: source year unknown (no 4-digit year in filename); stored as -1")
        validated.append((year, filename, frame, sha256_bytes(data), len(data)))

    # stable ordering: known years ascending, unknown-year files last, upload order within a year
    order = sorted(
        range(len(validated)),
        key=lambda i: (validated[i][0] is None, validated[i][0] if validated[i][0] is not None else 0, i),
    )
    blocks: list[pd.DataFrame] = []
    source_files: list[SourceFileInfo] = []
    offsets: dict[int, int] = {}
    seen_years: dict[int, list[str]] = {}
    for i in order:
        year, filename, frame, digest, size = validated[i]
        year_key = UNKNOWN_YEAR if year is None else year
        offset = offsets.get(year_key, 0)
        blocks.append(_year_block(frame, year_key, offset))
        offsets[year_key] = offset + len(frame)
        seen_years.setdefault(year_key, []).append(filename)
        source_files.append(
            SourceFileInfo(filename=filename, source_year=year, rows=len(frame), sha256=digest, bytes=size)
        )
    for year_key, names in seen_years.items():
        if len(names) > 1 and year_key != UNKNOWN_YEAR:
            warnings.append(
                f"{len(names)} files map to year {year_key} ({', '.join(names)}); rows were concatenated "
                "in upload order and row_index continues across files"
            )

    combined_hash = sha256_bytes("".join(sf.sha256 for sf in source_files).encode("ascii"))
    return DatasetBundle(
        dataset_id=f"ds_upload_{combined_hash[:12]}",
        frame=_assemble(blocks),
        source=source,
        source_files=source_files,
        warnings=warnings,
        created_at_utc=_now_utc(),
    )
