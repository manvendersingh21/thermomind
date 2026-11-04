"""Wiring: lazy singletons for the dataset repository, baseline model, investigation
store and Meta client, plus the synchronous investigation pipeline.

Sibling packages (``app.data``, ``app.analytics``, ``app.agent``) are imported
lazily inside functions so the API can start (and report a degraded health
status) even if one of them is missing or broken.
"""
from __future__ import annotations

import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app import config
from app.schemas import (
    HYPOTHESIS_KEYS,
    Investigation,
    InvestigationRequest,
    SampleRange,
    ScenarioInfo,
    ScenarioLabel,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.agent.meta_client import MetaClient
    from app.analytics.baseline import BaselineModel
    from app.data.repository import DatasetRepository
    from app.db.storage import InvestigationStore

log = logging.getLogger("thermomind.services")

UCI_DATASET_ID = "ds_uci_551"
MIN_WINDOW_ROWS = 24
MAX_WINDOW_ROWS = 2000
MIN_REFERENCE_ROWS = 24

_lock = threading.RLock()
_repo: "DatasetRepository | None" = None
_store: "InvestigationStore | None" = None
_model: "BaselineModel | None" = None
_model_checked = False
_model_mtime: float | None = None
_meta_client: "MetaClient | None" = None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_case_id() -> str:
    return f"case_{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------


def get_repo() -> "DatasetRepository":
    global _repo
    with _lock:
        if _repo is None:
            from app.data.repository import DatasetRepository

            _repo = DatasetRepository(Path(config.DB_PATH))
        return _repo


def get_store() -> "InvestigationStore":
    global _store
    with _lock:
        if _store is None:
            from app.db.storage import InvestigationStore

            _store = InvestigationStore(Path(config.DB_PATH))
        return _store


def _model_files_present() -> bool:
    model_dir = Path(config.MODEL_DIR)
    return (model_dir / "baseline_v1.joblib").is_file() and (model_dir / "baseline_v1.json").is_file()


def _model_files_mtime() -> float | None:
    """max(mtime) of the joblib + json pair, so a rewrite of either file triggers a reload."""
    try:
        return max((Path(config.MODEL_DIR) / name).stat().st_mtime
                   for name in ("baseline_v1.joblib", "baseline_v1.json"))
    except OSError:
        return None


def reload_model() -> "BaselineModel | None":
    """Force a (re)load of the baseline model from ``config.MODEL_DIR``; None if absent."""
    global _model, _model_checked, _model_mtime
    with _lock:
        _model_checked = True
        _model_mtime = _model_files_mtime()
        if not _model_files_present():
            _model = None
            return None
        try:
            from app.analytics.baseline import BaselineModel

            _model = BaselineModel.load(Path(config.MODEL_DIR))
            log.info("baseline model loaded: %s from %s", _model.version, config.MODEL_DIR)
        except Exception as exc:  # noqa: BLE001 - degraded mode, never crash the API
            log.warning("baseline model present but failed to load: %s", type(exc).__name__)
            _model = None
        return _model


def get_model(recheck: bool = False) -> "BaselineModel | None":
    """Cached baseline model. ``recheck=True`` re-inspects the files (used by health/startup)."""
    with _lock:
        if not _model_checked:
            return reload_model()
        if recheck or _model is None:
            mtime = _model_files_mtime()
            if mtime != _model_mtime:
                return reload_model()
        return _model


# ---------------------------------------------------------------------------
# GPU challenger (second opinion) — owned by the GPU-integration agent
# ---------------------------------------------------------------------------
# The challenger (``mlp_v1``, TorchBaselineModel) never replaces the production baseline; it only adds a second
# opinion to each investigation. Cached per (MODEL_DIR, weights mtime) so tests that repoint config.MODEL_DIR never
# see a stale model. torch is optional: any import/load failure yields None.

_challenger_lock = threading.Lock()
_challenger: Any = None
_challenger_key: tuple[str, float | None] | None = None


def _challenger_weights() -> Path:
    return Path(config.MODEL_DIR) / "mlp_v1.pt"


def get_challenger() -> Any:
    """Cached ``TorchBaselineModel`` (cuda:0 when available, else cpu) or None when absent/unloadable."""
    global _challenger, _challenger_key
    weights = _challenger_weights()
    try:
        mtime: float | None = weights.stat().st_mtime if (weights.with_suffix(".json")).is_file() else None
    except OSError:
        mtime = None
    key = (str(Path(config.MODEL_DIR)), mtime)
    with _challenger_lock:
        if key == _challenger_key:
            return _challenger
        _challenger_key = key
        _challenger = None
        if mtime is None:
            return None
        try:
            import pandas as pd

            from app.analytics.torch_baseline import TorchBaselineModel

            model = TorchBaselineModel.load(Path(config.MODEL_DIR), device=None)  # None -> cuda:0 if available
            model.predict(pd.DataFrame([model._x_mean], columns=model.features))  # warm-up (CUDA context/kernels)
            _challenger = model
            log.info("challenger model loaded: %s on %s", model.version, getattr(model, "_device", "cpu"))
        except Exception as exc:  # noqa: BLE001 - optional second opinion, never crash the API
            log.warning("challenger model present but failed to load: %s", type(exc).__name__)
            _challenger = None
        return _challenger


def get_meta_client() -> "MetaClient":
    global _meta_client
    with _lock:
        if _meta_client is None:
            from app.agent.meta_client import MetaClient

            _meta_client = MetaClient(
                api_key=config.meta_api_key(),
                base_url=config.META_BASE_URL,
                model=config.META_MODEL,
                timeout_s=config.META_TIMEOUT_S,
            )
        return _meta_client


def reset() -> None:
    """Drop all cached singletons (tests)."""
    global _repo, _store, _model, _model_checked, _model_mtime, _meta_client
    with _lock:
        _repo = None
        _store = None
        _model = None
        _model_checked = False
        _model_mtime = None
        _meta_client = None


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------


def uci_raw_files_present(raw_dir: Path | None = None) -> bool:
    raw_dir = Path(raw_dir or config.RAW_UCI_DIR)
    return all((raw_dir / f"gt_{y}.csv").is_file() for y in (2011, 2012, 2013, 2014, 2015))


def data_ready() -> bool:
    try:
        get_repo().get(UCI_DATASET_ID)
        return True
    except Exception:  # noqa: BLE001
        return False


def seed_uci_if_available() -> bool:
    """Seed the UCI dataset from the local raw dir. Never downloads. Returns True if seeded."""
    if not uci_raw_files_present():
        log.warning(
            "UCI raw files not found in %s; dataset not seeded (run `make data`).", config.RAW_UCI_DIR
        )
        return False
    try:
        bundle = get_repo().seed_uci(Path(config.RAW_UCI_DIR))
        log.info("dataset %s ready: %d rows, years %s", bundle.dataset_id, len(bundle.frame), bundle.years())
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("UCI seed failed: %s: %s", type(exc).__name__, str(exc)[:300])
        return False


def startup() -> None:
    seed_uci_if_available()
    try:  # uploads persisted under DATA_DIR/uploads survive a restart
        get_repo().restore_uploads(Path(config.DATA_DIR) / "uploads")
    except Exception as exc:  # noqa: BLE001
        log.warning("restoring uploaded datasets failed: %s", type(exc).__name__)
    if get_model(recheck=True) is None:
        log.warning("baseline model not found in %s (run `make train`).", config.MODEL_DIR)


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def get_scenarios() -> dict[str, ScenarioInfo]:
    from app.analytics.scenarios import SCENARIOS

    return SCENARIOS


def get_scenario(scenario_id: str) -> ScenarioInfo:
    scenarios = get_scenarios()
    if scenario_id not in scenarios:
        raise KeyError(f"unknown scenario_id '{scenario_id}' (expected one of {', '.join(scenarios)})")
    return scenarios[scenario_id]


def scenario_label_for(scenario: ScenarioInfo) -> ScenarioLabel:
    return "synthetic_overlay" if scenario.synthetic else "real_only"


def validate_window(start: int, end: int) -> None:
    """Raises ValueError (API -> 422) when the window is not usable."""
    if start < 0:
        raise ValueError(f"start_index must be >= 0 (got {start})")
    n = end - start
    if n < MIN_WINDOW_ROWS:
        raise ValueError(f"window must contain at least {MIN_WINDOW_ROWS} rows (got {n})")
    if n > MAX_WINDOW_ROWS:
        raise ValueError(f"window must contain at most {MAX_WINDOW_ROWS} rows (got {n})")


def reference_bounds(start: int) -> tuple[int, int]:
    """Reference rows are the (up to) 240 real rows immediately before the window."""
    return max(0, start - config.DEFAULT_REFERENCE_ROWS), start


# ---------------------------------------------------------------------------
# Investigation pipeline
# ---------------------------------------------------------------------------


def _deterministic_summary(analysis: Any) -> dict[str, Any]:
    hyps = []
    for key in HYPOTHESIS_KEYS:
        ev = analysis.hypothesis_evals.get(key)
        if ev is None:
            continue
        hyps.append(
            {
                "hypothesis_key": ev.hypothesis_key,
                "deterministic_support_score": float(ev.deterministic_support_score),
                "supporting_evidence_ids": list(ev.supporting_evidence_ids),
                "contradicting_evidence_ids": list(ev.contradicting_evidence_ids),
                "deterministic_notes": list(ev.deterministic_notes),
            }
        )
    # any extra keys the analytics module may add
    for key, ev in analysis.hypothesis_evals.items():
        if key not in HYPOTHESIS_KEYS:
            hyps.append(
                {
                    "hypothesis_key": ev.hypothesis_key,
                    "deterministic_support_score": float(ev.deterministic_support_score),
                    "supporting_evidence_ids": list(ev.supporting_evidence_ids),
                    "contradicting_evidence_ids": list(ev.contradicting_evidence_ids),
                    "deterministic_notes": list(ev.deterministic_notes),
                }
            )
    hyps.sort(key=lambda h: h["deterministic_support_score"], reverse=True)

    def notable(ev: Any) -> bool:
        return ev.data_quality != "pass" or bool(
            {"notable_deviation", "isolated_single_sensor", "out_of_training_range"} & set(ev.flags))

    notable_ids = [ev.evidence_id for ev in analysis.evidence if notable(ev)][:12]
    return {
        "note": "Deterministic heuristic summary computed from tool outputs; not a diagnosis. "
        "Human engineer review required.",
        "top_hypotheses": hyps,
        "notable_evidence_ids": notable_ids,
        "evidence_count": len(analysis.evidence),
    }


def run_investigation_pipeline(req: InvestigationRequest) -> Investigation:
    """repo.get -> window/reference frames -> apply_scenario -> analyze_case -> run_investigation -> persist.

    Raises KeyError (404) for unknown dataset/scenario, ValueError/IndexError (422) for bad windows.
    Agent-side failures are captured into a persisted ``failed`` investigation.
    """
    from app.agent.orchestrator import run_investigation
    from app.analytics.evidence import analyze_case
    from app.analytics.scenarios import apply_scenario

    scenario = get_scenario(req.scenario_id)
    validate_window(req.start_index, req.end_index)
    bundle = get_repo().get(req.dataset_id)

    window_frame = bundle.window(req.year, req.start_index, req.end_index)
    ref_start, ref_end = reference_bounds(req.start_index)
    if ref_end - ref_start < MIN_REFERENCE_ROWS:
        raise ValueError(
            f"at least {MIN_REFERENCE_ROWS} real reference rows must precede the window in year {req.year}; "
            f"start_index={req.start_index} leaves only {ref_end - ref_start}. Use start_index >= {MIN_REFERENCE_ROWS}."
        )
    reference_frame = bundle.window(req.year, ref_start, ref_end)

    case_id = new_case_id()
    created_at = now_utc()
    seed = scenario.default_seed if req.seed is None else int(req.seed)
    scenario_result = apply_scenario(window_frame, req.scenario_id, seed)
    window = SampleRange(source_year=req.year, start=req.start_index, end=req.end_index)
    reference = SampleRange(source_year=req.year, start=ref_start, end=ref_end)
    model = get_model()
    label = scenario_label_for(scenario)

    # The evidence engine must see the scenario-applied COPY; the raw window is never mutated.
    analysis = analyze_case(
        case_id,
        scenario_result.frame,
        reference_frame,
        scenario_result,
        model,
        window,
        reference,
        challenger=get_challenger(),
    )

    client: Any = None  # always resolved; run_investigation honours use_meta (and names the offline reason)
    try:
        candidate = get_meta_client()
        client = candidate if candidate.configured else None
    except Exception as exc:  # noqa: BLE001
        log.warning("meta client unavailable: %s", type(exc).__name__)
        client = None

    base = dict(
        case_id=case_id,
        created_at_utc=created_at,
        request=req,
        scenario=scenario,
        scenario_label=label,
        window=window,
        reference=reference,
        model_version=(model.version if model is not None else None),
        evidence=list(analysis.evidence),
        data_quality=analysis.data_quality,
        baseline=analysis.baseline,
        deterministic_summary=_deterministic_summary(analysis),
    )

    try:
        outcome = run_investigation(analysis, label, client, use_meta=bool(req.use_meta))
    except Exception as exc:  # noqa: BLE001 - persist a failed case instead of a 500
        log.exception("investigation %s failed in the agent stage", case_id)
        inv = Investigation(
            status="failed",
            completed_at_utc=now_utc(),
            meta_model=None,
            meta_used=False,
            mode="offline_preview",
            report=None,
            events=[],
            validation_errors=[],
            report_hash=None,
            error=f"agent stage failed: {type(exc).__name__}",
            **base,
        )
        get_store().save(inv)
        return inv

    mode = outcome.mode if outcome.mode in ("meta_live", "offline_preview") else "offline_preview"
    extra_summary = getattr(outcome, "deterministic_summary", None)
    if isinstance(extra_summary, dict) and extra_summary:
        base["deterministic_summary"] = {**base["deterministic_summary"], **extra_summary}
    inv = Investigation(
        status=outcome.status,
        completed_at_utc=now_utc(),
        meta_model=outcome.meta_model,
        meta_used=bool(outcome.meta_used),
        mode=mode,
        report=outcome.report,
        events=list(outcome.events),
        validation_errors=list(outcome.validation_errors),
        report_hash=outcome.report_hash,
        error=outcome.error,
        **base,
    )
    get_store().save(inv)
    from app.plant.work_requests import on_investigation_completed  # plant-ops routing (simulated in-app; never raises)
    on_investigation_completed(inv)
    try:  # collaboration layer: autonomy-policy log (agent_auto triage or requires_human); never raises
        from app.features.collab.autonomy import apply_autonomy_policy
        apply_autonomy_policy(inv)
    except Exception as exc:  # noqa: BLE001 - optional package
        log.info("collab policy unavailable: %s", type(exc).__name__)
    log.info(
        "investigation %s %s (scenario=%s mode=%s meta_used=%s evidence=%d)",
        case_id, inv.status, req.scenario_id, inv.mode, inv.meta_used, len(inv.evidence),
    )
    return inv
