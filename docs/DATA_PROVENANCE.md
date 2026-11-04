# Data provenance

## Source

| Field | Value |
|---|---|
| Data set | Gas Turbine CO and NOx Emission Data Set |
| Repository | UCI Machine Learning Repository, ID 551 |
| DOI | 10.24432/C5WC95 |
| URL | https://archive.ics.uci.edu/dataset/551/gas+turbine+co+and+nox+emission+data+set |
| Licence | CC BY 4.0 |
| Citation | Kaya, H., Tüfekci, P. & Gürgen, F. (2019). Gas Turbine CO and NOx Emission Data Set. UCI Machine Learning Repository. https://doi.org/10.24432/C5WC95 |
| Plant | Undisclosed gas-turbine power plant in Turkey |
| Period | 2011–2015 |
| Rows | 36,733 one-hour aggregates: 2011 = 7411, 2012 = 7628, 2013 = 7152, 2014 = 7158, 2015 = 7384 |
| Files | `gt_2011.csv` … `gt_2015.csv`, fetched by `make data` (`scripts/fetch_uci.py`) into `data/raw/uci_551/` (git-ignored); the script verifies headers and row counts and records sha256 per file |

## Columns (as published)

| Key | Name | Unit | Role in ThermoMind |
|---|---|---|---|
| AT | Ambient temperature | °C | model feature |
| AP | Ambient pressure | mbar | model feature |
| AH | Ambient humidity | % | model feature |
| AFDP | Air filter differential pressure | mbar | model feature; intake-restriction evidence |
| GTEP | Gas turbine exhaust pressure | mbar | model feature |
| TIT | Turbine inlet temperature | °C | model feature |
| TAT | Turbine after temperature | °C | model feature |
| TEY | Turbine energy yield | MWh | model target; kept as MWh, not converted to MW |
| CDP | Compressor discharge pressure | mbar (as published; unit and physical interpretation under validation) | model feature, used as an unscaled numeric value |
| CO | Carbon monoxide | mg/m³ | displayed only; excluded from the model (combustion output) |
| NOX | Nitrogen oxides | mg/m³ | displayed only; excluded from the model (combustion output) |

## What the data set does not contain

- **Row-level timestamps.** Rows are hourly aggregates in file order within each year. ThermoMind keeps `source_year` and a 0-based `row_index` per year and never fabricates dates. `DatasetSummary.has_timestamps=false`, `time_axis_type="ordered_hourly_sample_without_actual_timestamp"`, `Evidence.sample_range` uses row indices, and the UI prints `2014 • sample #1253`. The report validator rejects any date-like claim about UCI rows.
- **Fault labels.** There is no record of failures, maintenance or alarms. Nothing in ThermoMind is a labelled fault; residuals are deviations from a learned relation.
- **Load / dispatch signal.** Output changes caused by the operator cannot be separated from output changes caused by the machine.
- **Plant identity, turbine model, site metadata.**

## How ThermoMind handles it

- **Raw frames are read-only.** Scenario overlays operate on copies; `synthetic=true`, `scenario_label="synthetic_overlay"`, `is_synthetic` on each affected evidence item and `provenance_kind` (`real_observation` / `model_derived` / `synthetic_overlay` / `measured_plus_synthetic_overlay`) travel with every response.
- **Fixture.** `data/fixtures/gt_2014_sample300.csv` holds the first 300 real rows of `gt_2014.csv`, redistributed under CC BY 4.0, so tests and offline demos need no download.
- **Uploads.** `POST /api/datasets/upload` accepts CSVs with the same 11 columns; `source="USER_UPLOAD"`; sha256 and warnings are recorded. Year is inferred from the filename when present; otherwise rows are still ordered samples without timestamps.
- **Provenance notes** (`app.data.provenance.uci_provenance_notes()`) are returned by `GET /api/datasets/{id}` and shown on `/data`.

## Known data caveats

1. CDP values (roughly 10–15) are implausible for mbar at a compressor discharge; the source labels them mbar. We display the label as published and flag it as under validation. The model is unaffected because it uses the raw numeric value.
2. Single plant, single climate, 2011–2015 technology. Any generalisation claim would be unsupported.
3. The aggregation method behind each hourly row (mean? sample?) is not documented by the source beyond "hourly average".
4. Synthetic overlays reproduce *direction* of known physical tendencies (e.g. intake fouling raises AFDP and lowers output) with hand-chosen magnitudes; they are illustrations, not recorded events, and are described in full in each `ScenarioInfo.description`.
