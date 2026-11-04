# Data directory

- `raw/uci_551/` (git-ignored): the original `gt_2011.csv` … `gt_2015.csv` files from the UCI Gas Turbine CO and NOx Emission Data Set (ID 551, DOI 10.24432/C5WC95, CC BY 4.0). Fetched by `make data` / `scripts/fetch_uci.py`.
- `fixtures/gt_2014_sample300.csv`: first 300 rows of the real `gt_2014.csv`, redistributed under CC BY 4.0 for tests and offline demos. Attribution: Kaya, Tüfekci & Gürgen (2019), UCI Machine Learning Repository.
- `models/` (git-ignored): trained baseline artifacts produced by `make train`.

The dataset has **no row-level timestamps**. Rows are one-hour aggregates in file order; we keep `source_year` + `row_index` only and never fabricate dates.
