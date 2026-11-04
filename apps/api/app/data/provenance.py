"""Provenance helpers: honest notes about the UCI dataset and content hashing.

Everything here is deliberately plain-spoken. The notes are shown to users in
dataset detail views and must never overstate what the data contains.
"""
from __future__ import annotations

import hashlib

from app.schemas import UCI_CITATION, UCI_DOI, UCI_LICENSE, UCI_URL

UCI_PLANT_DESCRIPTION = "undisclosed Turkish gas-turbine plant"


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 digest of raw bytes (used for every source file)."""
    return hashlib.sha256(data).hexdigest()


def uci_provenance_notes() -> list[str]:
    """Human-readable, honest provenance notes for the UCI Gas Turbine data set (ID 551)."""
    return [
        "Source: UCI Machine Learning Repository data set 551, 'Gas Turbine CO and NOx Emission Data Set' "
        f"({UCI_URL}, DOI {UCI_DOI}).",
        "Measurements come from a real, undisclosed combined-cycle gas-turbine plant in north-western Turkey; "
        "plant identity, turbine model and site conditions are not published.",
        "Coverage: five calendar years, 2011 through 2015, one file per year (36,733 rows in total).",
        "Each row is an hourly aggregate of sensor readings. Rows are stored in file order within each year, "
        "which the publishers describe as chronological, but this is not guaranteed row by row.",
        "The data set contains NO row-level timestamps. ThermoMind keeps only source_year + row_index and never "
        "fabricates dates or clock times.",
        "There are NO verified fault, maintenance or failure labels in this data set. Any 'fault' shown in "
        "ThermoMind is either a synthetic overlay (labelled synthetic=true) or a model-derived flag, not a "
        "confirmed plant event.",
        "TEY (turbine energy yield) is published in MWh per hourly aggregate; it is kept as MWh and is not "
        "converted to MW.",
        "CDP (compressor discharge pressure) is published with unit 'mbar'; this unit is reported as published "
        "and is flagged as under validation because the magnitudes (~9-16) are more typical of bar.",
        "Ambient variables (AT, AP, AH) and the CO/NOx emissions are as published; no calibration or unit "
        "corrections have been applied.",
        f"License: {UCI_LICENSE} (Creative Commons Attribution 4.0). Citation: {UCI_CITATION}",
    ]


def upload_provenance_notes(filenames: list[str]) -> list[str]:
    """Provenance notes for user-uploaded CSV files (ThermoMind cannot vouch for their origin)."""
    return [
        "Source: user-uploaded CSV file(s): " + ", ".join(filenames) + ".",
        "ThermoMind cannot verify the plant, instrumentation, units or sampling interval of uploaded data; "
        "values are interpreted using the UCI column conventions (" "AT, AP, AH, AFDP, GTEP, TIT, TAT, TEY, CDP, CO, NOX).",
        "No row-level timestamps are stored; rows are kept in file order as source_year + row_index. "
        "The source year is inferred from the filename only (a four-digit year), otherwise it is unknown.",
        "No fault labels are assumed. Any anomaly shown is model-derived or a synthetic overlay.",
    ]
