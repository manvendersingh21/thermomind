# ThermoMind contracts

All types live in `apps/api/app/schemas.py` (Pydantic) and mirror into `apps/web/src/api/types.ts`.
**Do not rename fields.** Add fields only with a default.

## HTTP API (prefix `/api`, port 8000; Vite dev on 5173 proxies `/api`)

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/health` | – | `Health` |
| GET | `/api/demo/status` | – | `DemoStatus` |
| GET | `/api/datasets` | – | `DatasetSummary[]` |
| POST | `/api/datasets/seed-uci` | – (idempotent) | `DatasetSummary` (dataset_id = `ds_uci_551`) |
| POST | `/api/datasets/upload` | multipart `file` | `UploadResult` (400/413/422 on bad input) |
| GET | `/api/datasets/{id}` | – | `DatasetDetail` |
| GET | `/api/datasets/{id}/series?measure=AFDP&year=2014&start=0&limit=500&include_expected=false` | – | `SeriesResponse` (server downsamples to ≤2000 pts) |
| GET | `/api/models/evaluation` | – | `ModelEvaluation` (404 if not trained) |
| POST | `/api/models/train` | `{seed?: int}` | `ModelEvaluation` (local/admin only) |
| GET | `/api/scenarios` | – | `ScenarioInfo[]` |
| POST | `/api/scenarios/preview` | `ScenarioPreviewRequest` | `ScenarioPreviewResponse` |
| POST | `/api/investigations` | `InvestigationRequest` | `InvestigationCreated` (synchronous: runs the whole pipeline, returns when done; status `completed`/`needs_review`/`failed`) |
| GET | `/api/investigations` | – | `Investigation[]` (newest first; report+events included, evidence included) |
| GET | `/api/investigations/{case_id}` | – | `Investigation` |
| GET | `/api/investigations/{case_id}/evidence` | – | `Evidence[]` |
| GET | `/api/investigations/{case_id}/evidence/{evidence_id}` | – | `Evidence` |
| POST | `/api/investigations/{case_id}/review` | `ReviewRequest` | `Investigation` |
| GET | `/api/investigations/{case_id}/export.json` | – | full `Investigation` as download |

Errors: JSON `{"detail": "..."}` with proper status codes. Never 500 for user input problems. Never leak the API key.

## Python module interfaces (each owner implements exactly these)

### `app.data` (owner: Data agent)
```python
# app/data/uci_loader.py
MEASUREMENT_COLUMNS = ["AT","AP","AH","AFDP","GTEP","TIT","TAT","TEY","CDP","CO","NOX"]
def load_uci_dir(raw_dir: Path) -> "DatasetBundle"      # reads gt_2011..gt_2015.csv; raises FileNotFoundError
def load_csv_files(files: list[tuple[str, bytes]], source: str = "USER_UPLOAD") -> "DatasetBundle"  # raises CsvValidationError
# app/data/validator.py
class CsvValidationError(ValueError): ...  # .message, .status_code (400/413/422)
def validate_csv_bytes(filename: str, data: bytes, max_bytes: int) -> tuple[pd.DataFrame, list[str]]  # returns (frame with MEASUREMENT_COLUMNS, warnings)
def infer_year_from_filename(filename: str) -> int | None
# app/data/repository.py
@dataclass
class DatasetBundle:
    dataset_id: str
    frame: pd.DataFrame           # columns: source_year(int), row_index(int, 0-based per year), + MEASUREMENT_COLUMNS (float64)
    source: str
    source_files: list[SourceFileInfo]
    warnings: list[str]
    created_at_utc: str
    def summary(self) -> DatasetSummary
    def detail(self) -> DatasetDetail
    def year_frame(self, year: int) -> pd.DataFrame          # rows for one year, sorted by row_index, index reset
    def window(self, year: int, start: int, end: int) -> pd.DataFrame  # slice [start,end) of year_frame; raises IndexError if out of range
class DatasetRepository:
    def __init__(self, db_path: Path | None = None)
    def register(self, bundle: DatasetBundle) -> DatasetBundle
    def get(self, dataset_id: str) -> DatasetBundle          # raises KeyError
    def list(self) -> list[DatasetSummary]
    def seed_uci(self, raw_dir: Path) -> DatasetBundle       # idempotent; dataset_id "ds_uci_551"
    def series(self, dataset_id, measure, year, start, limit, max_points=2000) -> SeriesResponse
# app/data/provenance.py
def uci_provenance_notes() -> list[str]
def sha256_bytes(data: bytes) -> str
```

### `app.analytics` (owner: ML agent)
```python
# app/analytics/train.py
def train_baseline(frame: pd.DataFrame, model_dir: Path, seed: int = 42) -> ModelEvaluation
#   chronological: train 2011–2013, validation 2014, holdout 2015 (falls back to 70/15/15 ordered split if <3 years, note in .notes)
#   writes model_dir/baseline_v1.joblib + model_dir/baseline_v1.json (ModelEvaluation)
# app/analytics/baseline.py
class BaselineModel:
    @classmethod
    def load(cls, model_dir: Path) -> "BaselineModel"      # raises FileNotFoundError
    evaluation: ModelEvaluation
    version: str                                           # == evaluation.model_version
    def predict(self, frame: pd.DataFrame) -> np.ndarray   # expected TEY per row (uses FEATURE_KEYS)
    def residuals(self, frame) -> np.ndarray               # observed - expected
    def out_of_range_counts(self, frame) -> dict[str, int]
# app/analytics/scenarios.py
SCENARIOS: dict[str, ScenarioInfo]
@dataclass
class ScenarioResult:
    scenario_id: str; synthetic: bool; seed: int
    frame: pd.DataFrame                 # COPY with overlay applied (same columns as input)
    transformations: list[Transformation]
    affected_measurements: list[str]
def apply_scenario(window: pd.DataFrame, scenario_id: str, seed: int | None = None) -> ScenarioResult   # never mutates input; raises KeyError for unknown id
# app/analytics/evidence.py
@dataclass
class CaseAnalysis:
    case_id: str
    window: SampleRange; reference: SampleRange
    window_frame: pd.DataFrame          # overlay applied (or real for S01)
    reference_frame: pd.DataFrame       # real reference rows (preceding window)
    scenario: ScenarioResult
    evidence: list[Evidence]
    data_quality: DataQualityReport
    baseline: BaselineComparison | None
    hypothesis_evals: dict[str, HypothesisEvaluation]   # keyed by HYPOTHESIS_KEYS
def analyze_case(case_id, window_frame, reference_frame, scenario: ScenarioResult, model: BaselineModel | None, window: SampleRange, reference: SampleRange) -> CaseAnalysis
# app/analytics/anomaly.py — helpers used by evidence.py (window vs reference stats, z-scores, spike detection)
```

### `app.agent` (owner: Meta agent)
```python
# app/agent/meta_client.py
class MetaClient:
    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_s: float)
    @property
    def configured(self) -> bool
    def chat(self, messages: list[dict], tools: list[dict] | None, max_tokens: int, response_format: dict | None = None) -> "ChatResult"
    #   ChatResult: .message (dict as returned, incl tool_calls), .usage (dict), .latency_ms, .model, .finish_reason
    def ping(self) -> dict   # {"ok": bool, "model": str, "latency_ms": int, "error": str|None}; redacted
# app/agent/tools.py
TOOL_SPECS: list[dict]  # OpenAI function-tool JSON for: get_sensor_window, get_baseline_comparison, evaluate_hypothesis, get_data_quality, lookup_reference
class ToolRunner:
    def __init__(self, analysis: CaseAnalysis)
    def run(self, name: str, args: dict) -> tuple[dict, list[str]]  # (json-serializable result, evidence_ids returned); raises ToolError for unknown tool / bad args
# app/agent/orchestrator.py
@dataclass
class InvestigationOutcome:
    report: DiagnosticReport | None; events: list[AgentEvent]; status: InvestigationStatus
    meta_used: bool; meta_model: str | None; mode: str; validation_errors: list[str]; report_hash: str | None; error: str | None
def run_investigation(analysis: CaseAnalysis, scenario_label: str, client: MetaClient | None, use_meta: bool = True) -> InvestigationOutcome
#   - if client configured and use_meta: real multi-turn tool loop with Muse Spark, validate, one bounded rewrite, else needs_review with deterministic summary
#   - else: offline_preview built from deterministic tools (mode="offline_preview", meta_used=False)
# app/agent/report_validator.py
def validate_report(raw: dict | str, case_id: str, known_evidence_ids: set[str], scenario_label: str) -> tuple[DiagnosticReport | None, list[str]]
def report_hash(report: DiagnosticReport) -> str
```

### `app.api` + `app.db` (owner: Backend agent)
- `app/main.py`: FastAPI app, CORS allowlist (localhost:5173), routers, static serving of `apps/web/dist` if present (SPA fallback), startup loads dataset/model if available.
- `app/db/storage.py`: `InvestigationStore` (SQLite via sqlite3; JSON blobs): `save(inv)`, `get(case_id)`, `list()`, `set_review(case_id, review)`.
- `app/api/investigations.py` orchestrates: repo.get → window/reference frames → apply_scenario → analyze_case → run_investigation → persist.

## Scenario defaults
Window: year 2014, rows [1200, 1320) (120 hourly samples). Reference: 240 rows immediately before (960–1200), always real. Seed 42.

## Hard rules
- Raw frames are never mutated; overlays are copies; `synthetic` flag propagates to every response.
- Evidence IDs: `ev_<metric_slug>_<nn>`; the agent may only cite IDs returned by tools.
- No timestamps are ever fabricated for UCI rows (`timestamp: null`, show `2014 • sample #1253`).
- No control actions anywhere. Reports are `draft_requires_human_review`.
