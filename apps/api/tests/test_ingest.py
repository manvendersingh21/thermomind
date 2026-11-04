"""Tests for the app.data layer (validator, loaders, repository, provenance)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import config
from app.data.provenance import sha256_bytes, uci_provenance_notes
from app.data.repository import DatasetBundle, DatasetRepository
from app.data.uci_loader import MEASUREMENT_COLUMNS, load_csv_files, load_uci_dir
from app.data.validator import CsvValidationError, infer_year_from_filename, validate_csv_bytes
from app.schemas import MEASUREMENT_KEYS, UCI_SOURCE_ID, DatasetDetail, DatasetSummary, SeriesResponse

HEADER = "AT,AP,AH,AFDP,GTEP,TIT,TAT,TEY,CDP,CO,NOX"
ROW1 = "4.5878,1018.7,83.675,3.5758,23.979,1086.2,549.83,134.67,11.898,0.32663,81.952"
ROW2 = "4.2932,1018.3,84.235,3.5709,23.951,1086.1,550.05,134.67,11.892,0.44784,82.377"
ROW3 = "5.1000,1017.9,80.100,3.6000,24.100,1086.0,549.90,135.10,11.900,0.40000,80.000"
MAX = 10 * 1024 * 1024
FIXTURE = Path(config.FIXTURE_DIR) / "gt_2014_sample300.csv"
RAW_DIR = Path(config.RAW_UCI_DIR)


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def synthetic_rows(n: int, seed: int = 0) -> list[str]:
    rng = np.random.default_rng(seed)
    base = [float(x) for x in ROW1.split(",")]
    out = []
    for _ in range(n):
        vals = [b + rng.normal(0, 0.01) for b in base]
        out.append(",".join(f"{v:.5f}" for v in vals))
    return out


@pytest.fixture
def repo(tmp_path: Path) -> DatasetRepository:
    return DatasetRepository(db_path=tmp_path / "registry" / "test.db")


# --------------------------------------------------------------------------- validator


def test_exact_header_maps_to_measurement_columns():
    assert MEASUREMENT_COLUMNS == MEASUREMENT_KEYS
    frame, warnings = validate_csv_bytes("gt_2014.csv", csv_bytes(ROW1, ROW2), MAX)
    assert list(frame.columns) == MEASUREMENT_COLUMNS
    assert len(frame) == 2
    assert all(frame[c].dtype == np.float64 for c in MEASUREMENT_COLUMNS)
    assert frame.loc[0, "AT"] == pytest.approx(4.5878)
    assert frame.loc[1, "NOX"] == pytest.approx(82.377)
    assert warnings == []


def test_extra_column_is_allowed_with_warning():
    data = csv_bytes(ROW1 + ",abc", ROW2 + ",def", header=HEADER + ",Comment")
    frame, warnings = validate_csv_bytes("x.csv", data, MAX)
    assert list(frame.columns) == MEASUREMENT_COLUMNS
    assert len(frame) == 2
    assert any("extra column" in w and "Comment" in w for w in warnings)


def test_missing_tey_column_is_422_and_lists_it():
    cols = HEADER.split(",")
    cols.remove("TEY")
    rows = [",".join(r.split(",")[:7] + r.split(",")[8:]) for r in (ROW1, ROW2)]
    with pytest.raises(CsvValidationError) as excinfo:
        validate_csv_bytes("x.csv", csv_bytes(*rows, header=",".join(cols)), MAX)
    assert excinfo.value.status_code == 422
    assert "TEY" in excinfo.value.message


def test_bad_numeric_cells_become_nan_with_warning_and_too_many_is_422():
    bad = ROW1.replace("134.67", "oops")
    frame, warnings = validate_csv_bytes("x.csv", csv_bytes(bad, ROW2, ROW3), MAX)
    assert math.isnan(frame.loc[0, "TEY"])
    assert frame.loc[1, "TEY"] == pytest.approx(134.67)
    assert any("1 non-numeric" in w and "TEY=1" in w for w in warnings)

    # > 20% of cells non-numeric -> unusable
    garbage = ",".join(["x"] * 11)
    with pytest.raises(CsvValidationError) as excinfo:
        validate_csv_bytes("x.csv", csv_bytes(garbage, garbage, ROW1), MAX)
    assert excinfo.value.status_code == 422


def test_oversized_file_is_413():
    data = csv_bytes(*synthetic_rows(50))
    with pytest.raises(CsvValidationError) as excinfo:
        validate_csv_bytes("big.csv", data, max_bytes=len(data) - 1)
    assert excinfo.value.status_code == 413
    # exactly at the limit is fine
    frame, _ = validate_csv_bytes("big.csv", data, max_bytes=len(data))
    assert len(frame) == 50


@pytest.mark.parametrize("name", ["../gt_2014.csv", "/etc/passwd", "..\\x.csv", "dir/x.csv", "", ".."])
def test_path_traversal_filename_rejected(name: str):
    with pytest.raises(CsvValidationError) as excinfo:
        validate_csv_bytes(name, csv_bytes(ROW1), MAX)
    assert excinfo.value.status_code == 400


def test_whitespace_in_header_and_cells_is_tolerated():
    header = " AT , AP,AH ,AFDP, GTEP,TIT, TAT,TEY , CDP,CO , NOX "
    row = "  4.5878 , 1018.7 ,83.675, 3.5758,23.979 ,1086.2, 549.83, 134.67 ,11.898, 0.32663 , 81.952 "
    frame, warnings = validate_csv_bytes("x.csv", csv_bytes(row, header=header), MAX)
    assert list(frame.columns) == MEASUREMENT_COLUMNS
    assert frame.loc[0, "AT"] == pytest.approx(4.5878)
    assert frame.loc[0, "NOX"] == pytest.approx(81.952)
    assert not any("non-numeric" in w for w in warnings)


def test_empty_and_header_only_and_non_utf8_files():
    with pytest.raises(CsvValidationError) as e1:
        validate_csv_bytes("x.csv", b"", MAX)
    assert e1.value.status_code == 422
    with pytest.raises(CsvValidationError) as e2:
        validate_csv_bytes("x.csv", (HEADER + "\n").encode(), MAX)
    assert e2.value.status_code == 422
    with pytest.raises(CsvValidationError) as e3:
        validate_csv_bytes("x.csv", b"\xff\xfe\x00\x01" + csv_bytes(ROW1), MAX)
    assert e3.value.status_code == 400


def test_formula_cells_are_neutralised_as_non_numeric():
    evil = ROW1.replace("4.5878", "=1+1").replace("0.32663", "@SUM(A1)")
    frame, warnings = validate_csv_bytes("x.csv", csv_bytes(evil, ROW2, ROW3), MAX)
    assert math.isnan(frame.loc[0, "AT"])
    assert math.isnan(frame.loc[0, "CO"])
    assert frame.loc[0, "AP"] == pytest.approx(1018.7)
    assert any("non-numeric" in w for w in warnings)
    # a plain signed number is still numeric
    frame2, _ = validate_csv_bytes("x.csv", csv_bytes(ROW1.replace("4.5878", "+4.5878")), MAX)
    assert frame2.loc[0, "AT"] == pytest.approx(4.5878)


def test_out_of_range_and_duplicates_are_warnings_not_errors():
    hot = ROW1.replace("4.5878", "99.0")  # AT outside plausible range
    frame, warnings = validate_csv_bytes("x.csv", csv_bytes(hot, ROW2, ROW2), MAX)
    assert len(frame) == 3
    assert any("AT" in w and "plausible range" in w for w in warnings)
    assert any("duplicate" in w for w in warnings)


def test_infer_year_from_filename():
    assert infer_year_from_filename("gt_2014.csv") == 2014
    assert infer_year_from_filename("gt_2014_sample300.csv") == 2014
    assert infer_year_from_filename("some/dir/plant_2013_export.csv") == 2013
    assert infer_year_from_filename("plant.csv") is None
    assert infer_year_from_filename("rows_300000.csv") is None


# --------------------------------------------------------------------------- loaders


def test_multi_file_year_grouping_and_ordering():
    files = [
        ("gt_2015.csv", csv_bytes(*synthetic_rows(3, seed=1))),
        ("gt_2013.csv", csv_bytes(*synthetic_rows(2, seed=2))),
        ("misc.csv", csv_bytes(*synthetic_rows(2, seed=3))),
        ("gt_2014.csv", csv_bytes(*synthetic_rows(4, seed=4))),
    ]
    bundle = load_csv_files(files)
    assert bundle.source == "USER_UPLOAD"
    assert list(bundle.frame.columns) == ["source_year", "row_index"] + MEASUREMENT_COLUMNS
    assert bundle.frame["source_year"].tolist() == [2013, 2013, 2014, 2014, 2014, 2014, 2015, 2015, 2015, -1, -1]
    assert bundle.frame["row_index"].tolist() == [0, 1, 0, 1, 2, 3, 0, 1, 2, 0, 1]
    assert bundle.summary().years == [2013, 2014, 2015]
    assert bundle.rows_per_year() == {"unknown": 2, "2013": 2, "2014": 4, "2015": 3}
    assert any("source year unknown" in w for w in bundle.warnings)
    assert [sf.source_year for sf in bundle.source_files] == [2013, 2014, 2015, None]
    assert all(sf.sha256 == sha256_bytes(dict(files)[sf.filename]) for sf in bundle.source_files)
    assert bundle.dataset_id.startswith("ds_upload_")
    assert load_csv_files(files).dataset_id == bundle.dataset_id  # content-addressed, idempotent


def test_row_order_preserved_and_row_index_matches_file_order():
    data = FIXTURE.read_bytes() if FIXTURE.is_file() else csv_bytes(*synthetic_rows(300, seed=5))
    expected = pd.read_csv(pd.io.common.BytesIO(data))
    bundle = load_csv_files([("gt_2014_sample300.csv", data)])
    yf = bundle.year_frame(2014)
    assert len(yf) == 300
    assert yf["row_index"].tolist() == list(range(300))
    for col in MEASUREMENT_COLUMNS:
        np.testing.assert_allclose(yf[col].to_numpy(), expected[col].to_numpy())
    assert bundle.source_files[0].rows == 300
    assert bundle.source_files[0].bytes == len(data)


def test_no_timestamp_field_anywhere():
    bundle = load_csv_files([("gt_2014.csv", csv_bytes(ROW1, ROW2))])
    summary = bundle.summary()
    assert isinstance(summary, DatasetSummary)
    assert summary.has_timestamps is False
    assert summary.time_axis_type == "ordered_hourly_sample_without_actual_timestamp"
    assert not any("time" in c.lower() or "date" in c.lower() for c in bundle.frame.columns)
    detail = bundle.detail()
    assert isinstance(detail, DatasetDetail)
    assert detail.has_timestamps is False
    assert "timestamp" not in detail.model_dump()


def test_detail_measurement_stats_and_nan_handling():
    bad = ROW1.replace("134.67", "n/a")
    bundle = load_csv_files([("gt_2014.csv", csv_bytes(bad, ROW2, ROW3))])
    detail = bundle.detail()
    stats = {m.key: m for m in detail.measurements}
    assert set(stats) == set(MEASUREMENT_COLUMNS)
    assert stats["TEY"].count == 2 and stats["TEY"].missing == 1
    assert stats["TEY"].min == pytest.approx(134.67)
    assert stats["TEY"].max == pytest.approx(135.10)
    assert stats["TEY"].unit == "MWh"
    assert stats["AT"].missing == 0
    assert detail.rows_per_year == {"2014": 3}
    assert detail.provenance_notes  # uploads also get honest notes
    detail.model_dump_json()  # must be JSON serialisable (no NaN)


# --------------------------------------------------------------------------- repository


@pytest.mark.skipif(not RAW_DIR.is_dir() or not (RAW_DIR / "gt_2015.csv").is_file(), reason="raw UCI dir missing")
def test_seed_uci_idempotent_and_row_count(repo: DatasetRepository):
    b1 = repo.seed_uci(RAW_DIR)
    b2 = repo.seed_uci(RAW_DIR)
    assert b1 is b2
    assert b1.dataset_id == "ds_uci_551"
    assert b1.source == UCI_SOURCE_ID
    s = b1.summary()
    assert s.row_count == 36733
    assert s.years == [2011, 2012, 2013, 2014, 2015]
    assert s.has_timestamps is False
    assert s.source_license == "CC-BY-4.0" and s.citation and s.source_url and s.plant
    assert b1.rows_per_year() == {"2011": 7411, "2012": 7628, "2013": 7152, "2014": 7158, "2015": 7384}
    assert len(b1.source_files) == 5 and all(len(sf.sha256) == 64 for sf in b1.source_files)
    assert len(repo.list()) == 1
    rows = repo.registry_rows()
    assert [r["dataset_id"] for r in rows] == ["ds_uci_551"]
    assert rows[0]["metadata"]["row_count"] == 36733
    # the scenario default window exists
    w = b1.window(2014, 1200, 1320)
    assert len(w) == 120 and w["row_index"].iloc[0] == 1200


def test_load_uci_dir_missing_files_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_uci_dir(tmp_path)
    (tmp_path / "gt_2011.csv").write_bytes(csv_bytes(ROW1))
    with pytest.raises(FileNotFoundError) as excinfo:
        load_uci_dir(tmp_path)
    assert "gt_2012.csv" in str(excinfo.value)


def test_series_downsampling_and_end_exclusive(repo: DatasetRepository):
    bundle = load_csv_files([("gt_2014.csv", csv_bytes(*synthetic_rows(1000, seed=7)))])
    repo.register(bundle)
    assert repo.get(bundle.dataset_id) is bundle

    resp = repo.series(bundle.dataset_id, "AFDP", 2014, start=10, limit=20)
    assert isinstance(resp, SeriesResponse)
    assert (resp.start, resp.end) == (10, 30)
    assert [p.row_index for p in resp.points] == list(range(10, 30))  # end exclusive
    assert resp.downsample_factor == 1
    assert resp.total_rows_in_year == 1000
    assert resp.unit == "mbar" and resp.synthetic is False and resp.provenance_kind == "real_observation"
    assert resp.source == "USER_UPLOAD"
    assert resp.points[0].value == pytest.approx(bundle.year_frame(2014).loc[10, "AFDP"])

    small = repo.series(bundle.dataset_id, "TEY", 2014, start=0, limit=1000, max_points=100)
    assert len(small.points) <= 100
    assert small.downsample_factor == 10
    assert small.points[0].row_index == 0 and small.points[1].row_index == 10
    assert (small.start, small.end) == (0, 1000)

    # bounds clamp
    clamped = repo.series(bundle.dataset_id, "TEY", 2014, start=990, limit=500)
    assert (clamped.start, clamped.end) == (990, 1000) and len(clamped.points) == 10
    beyond = repo.series(bundle.dataset_id, "TEY", 2014, start=5000, limit=10)
    assert beyond.points == [] and beyond.start == 1000 and beyond.end == 1000

    with pytest.raises(KeyError):
        repo.series("nope", "TEY", 2014, 0, 10)
    with pytest.raises(KeyError):
        repo.series(bundle.dataset_id, "timestamp", 2014, 0, 10)
    with pytest.raises(KeyError):
        repo.series(bundle.dataset_id, "TEY", 1999, 0, 10)
    with pytest.raises(KeyError):
        repo.get("missing")


def test_series_nan_values_become_none(repo: DatasetRepository):
    bad = ROW1.replace("3.5758", "broken")
    bundle = repo.register(load_csv_files([("gt_2014.csv", csv_bytes(bad, ROW2))]))
    resp = repo.series(bundle.dataset_id, "AFDP", 2014, 0, 10)
    assert resp.points[0].value is None
    assert resp.points[1].value == pytest.approx(3.5709)
    resp.model_dump_json()


def test_window_index_error_and_copy_semantics():
    bundle = load_csv_files([("gt_2014.csv", csv_bytes(*synthetic_rows(50, seed=9)))])
    w = bundle.window(2014, 10, 20)
    assert len(w) == 10 and w["row_index"].tolist() == list(range(10, 20))
    for bad in [(2014, -1, 10), (2014, 0, 51), (2014, 20, 10), (2014, 10, 10), (2013, 0, 5)]:
        with pytest.raises(IndexError):
            bundle.window(*bad)
    # mutating a window must never touch the raw frame
    original = bundle.frame.loc[10, "TEY"]
    w.loc[0, "TEY"] = -999.0
    assert bundle.frame.loc[10, "TEY"] == original


def test_registry_persists_rows_in_sqlite(tmp_path: Path):
    db = tmp_path / "deep" / "dir" / "reg.db"
    repo = DatasetRepository(db_path=db)
    assert db.is_file()
    bundle = repo.register(load_csv_files([("gt_2012.csv", csv_bytes(ROW1))]))
    repo.register(bundle)  # re-register is an upsert, not a duplicate
    rows = DatasetRepository(db_path=db).registry_rows()
    assert len(rows) == 1 and rows[0]["source"] == "USER_UPLOAD"
    assert rows[0]["metadata"]["years"] == [2012]


def test_uci_provenance_notes_are_honest():
    notes = uci_provenance_notes()
    text = " ".join(notes).lower()
    assert len(notes) >= 6
    for needle in ["turk", "2011", "2015", "hourly", "no row-level timestamps", "no verified fault", "mwh", "cdp", "cc-by-4.0", "10.24432/c5wc95"]:
        assert needle in text, needle
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
