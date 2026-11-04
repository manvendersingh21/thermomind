#!/usr/bin/env python3
"""Download the UCI Gas Turbine CO and NOx Emission Data Set (ID 551) into data/raw/uci_551.

Usage (from repo root):  .venv/bin/python scripts/fetch_uci.py [--force]

* Skips the download when all five gt_YYYY.csv files are already present.
* Uses only the standard library (urllib + zipfile) with a network timeout.
* Verifies the five files exist, have the exact expected header, and prints row counts.
Exit code 0 on success, 1 on any problem (offline, bad zip, wrong header).
"""
from __future__ import annotations

import csv
import io
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

try:
    from app import config  # type: ignore

    UCI_ZIP_URL = config.UCI_ZIP_URL
    RAW_DIR = Path(config.RAW_UCI_DIR)
except Exception:  # pragma: no cover - fallback when the venv is not active
    UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/551/gas+turbine+co+and+nox+emission+data+set.zip"
    RAW_DIR = REPO_ROOT / "data" / "raw" / "uci_551"

YEARS = [2011, 2012, 2013, 2014, 2015]
EXPECTED_HEADER = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"]
EXPECTED_ROWS = {2011: 7411, 2012: 7628, 2013: 7152, 2014: 7158, 2015: 7384}
TIMEOUT_S = 60


def expected_files() -> dict[int, Path]:
    return {year: RAW_DIR / f"gt_{year}.csv" for year in YEARS}


def download_zip(url: str) -> bytes:
    print(f"Downloading {url} (timeout {TIMEOUT_S}s) ...")
    req = urllib.request.Request(url, headers={"User-Agent": "ThermoMind/0.1 (fetch_uci.py)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https URL
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ERROR: HTTP {exc.code} while downloading the UCI zip: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SystemExit(
            "ERROR: could not reach archive.ics.uci.edu (offline or blocked?): "
            f"{exc}. Download the zip manually and unpack gt_2011.csv..gt_2015.csv into {RAW_DIR}"
        ) from exc


def extract(zip_bytes: bytes) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"ERROR: downloaded file is not a zip archive ({exc})") from exc
    wanted = {f"gt_{year}.csv": year for year in YEARS}
    found = 0
    with zf:
        for member in zf.infolist():
            base = Path(member.filename).name  # flatten; never trust archive paths
            if base in wanted and not member.is_dir():
                target = RAW_DIR / base
                target.write_bytes(zf.read(member))
                found += 1
                print(f"  extracted {base} ({member.file_size:,} bytes)")
    if found != len(YEARS):
        raise SystemExit(f"ERROR: zip contained {found} of {len(YEARS)} expected gt_YYYY.csv files")


def verify() -> int:
    """Check files + headers, print row counts. Returns total rows; exits 1 on problems."""
    total = 0
    problems: list[str] = []
    for year, path in expected_files().items():
        if not path.is_file():
            problems.append(f"{path.name}: missing")
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = [h.strip() for h in next(reader, [])]
            rows = sum(1 for row in reader if any(cell.strip() for cell in row))
        if header != EXPECTED_HEADER:
            problems.append(f"{path.name}: unexpected header {header}")
        expected = EXPECTED_ROWS.get(year)
        note = "" if expected is None or expected == rows else f"  (expected {expected})"
        print(f"  {path.name}: {rows:,} rows{note}")
        total += rows
    print(f"  total: {total:,} rows")
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        raise SystemExit(1)
    return total


def main(argv: list[str]) -> int:
    force = "--force" in argv
    files = expected_files()
    present = all(p.is_file() for p in files.values())
    if present and not force:
        print(f"All five UCI files already present in {RAW_DIR}; skipping download (use --force to refetch).")
    else:
        extract(download_zip(UCI_ZIP_URL))
    print("Verifying files and headers ...")
    verify()
    print("OK. License CC BY 4.0 — Kaya, Tüfekci & Gürgen (2019), UCI ML Repository, DOI 10.24432/C5WC95.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
