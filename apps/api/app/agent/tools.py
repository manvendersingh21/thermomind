"""Read-only tools the Meta model may call during an investigation.

ToolRunner is duck-typed over the CaseAnalysis contract (contracts/api.md): it only needs
attributes case_id, window, reference, window_frame, reference_frame, scenario, evidence,
data_quality, baseline, hypothesis_evals.  The scenario's hidden label/expected_behavior is
never exposed; only scenario_label and which measurements carry a synthetic overlay are.
"""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from app.schemas import HYPOTHESIS_KEYS, MEASUREMENT_KEYS, MEASUREMENTS, UCI_URL

MAX_WINDOW_MEASUREMENTS = 11


class ToolError(ValueError):
    """Bad tool name or arguments. Message is safe to show to the model and the UI."""


REFERENCE_TOPICS = ["intake_filter_fouling", "compressor_discharge_pressure",
                    "sensor_validation", "ambient_effects"]

# Bundled background notes. URLs are general public references only (no plant manuals).
_REFERENCE_NOTES: dict[str, dict[str, Any]] = {
    "intake_filter_fouling": {
        "topic": "intake_filter_fouling",
        "notes": [
            "A rising differential pressure across the inlet air filter (AFDP) generally indicates "
            "increasing restriction (dust loading, icing, blocked media). A gas turbine's output is "
            "sensitive to inlet pressure loss, so an inlet restriction tends to reduce mass flow and "
            "energy yield for the same ambient conditions.",
            "Restriction is usually gradual (ramp-like) rather than a step; a sudden step in AFDP "
            "alone with no change in compressor or output measurements is more consistent with a "
            "sensor or tubing issue than with a real restriction.",
            "This is generic background, not a plant-specific statement; the UCI dataset has no "
            "maintenance records, so filter changes cannot be confirmed from the data.",
        ],
        "urls": ["https://en.wikipedia.org/wiki/Gas_turbine", "https://en.wikipedia.org/wiki/Air_filter"],
    },
    "compressor_discharge_pressure": {
        "topic": "compressor_discharge_pressure",
        "notes": [
            "Compressor discharge pressure (CDP) rises with compressor mass flow and load; it is "
            "normally strongly correlated with turbine energy yield and inlet temperature (TIT).",
            "In the UCI dataset CDP is published in 'mbar' with typical values around 10-15, which is "
            "physically implausible for an absolute discharge pressure; the unit is treated as "
            "'as published, under validation' (likely bar). Do not re-scale it.",
            "A CDP change that is inconsistent with TEY and TIT may point to a measurement problem "
            "rather than a process change.",
        ],
        "urls": ["https://en.wikipedia.org/wiki/Axial_compressor", UCI_URL],
    },
    "sensor_validation": {
        "topic": "sensor_validation",
        "notes": [
            "A single sensor moving while physically coupled sensors stay flat is the classic "
            "signature of a measurement issue (drift, offset, stuck value, wiring). Cross-check with "
            "redundant or physically related channels before trusting one deviating signal.",
            "Hourly aggregates (as in the UCI set) hide sub-hour behaviour; spikes may be smoothed and "
            "cannot be used to diagnose fast transients.",
            "Without calibration records, sensor issues can only be stated as a hypothesis, never confirmed.",
        ],
        "urls": ["https://en.wikipedia.org/wiki/Measurement_uncertainty"],
    },
    "ambient_effects": {
        "topic": "ambient_effects",
        "notes": [
            "Gas turbine output decreases as ambient temperature rises (lower air density, lower mass "
            "flow) and increases with ambient pressure; humidity has a smaller effect. A fall in TEY "
            "that is explained by AT/AP changes is an operating-condition effect, not a fault.",
            "The baseline model in this system uses AT, AP, AH among its inputs, so its residual "
            "(observed minus expected TEY) is partly ambient-corrected; a residual near zero while "
            "TEY drops suggests ambient/operating explanation.",
            "Load dispatch changes also alter TEY; the dataset has no dispatch or fuel-flow signal.",
        ],
        "urls": ["https://en.wikipedia.org/wiki/Gas_turbine"],
    },
}

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_sensor_window",
            "description": (
                "Summary statistics and first/last values for one or more measurements over a row "
                "range. Rows are hourly samples identified by (source_year, row_index); there are no "
                "timestamps. The range must lie inside the reference+case window of this case."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "measurements": {
                        "type": "array",
                        "items": {"type": "string", "enum": MEASUREMENT_KEYS},
                        "description": "Measurement keys, e.g. [\"AFDP\",\"TEY\",\"CDP\"].",
                    },
                    "start_index": {"type": "integer", "description": "First row index (inclusive)."},
                    "end_index": {"type": "integer", "description": "Last row index (exclusive)."},
                },
                "required": ["measurements", "start_index", "end_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_baseline_comparison",
            "description": (
                "Model-derived comparison of observed vs expected turbine energy yield (TEY) for the "
                "case window, with the evidence ids of model-derived evidence."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_hypothesis",
            "description": (
                "Deterministic (heuristic) evaluation of one hypothesis with the full supporting and "
                "contradicting evidence objects, including their numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_key": {"type": "string", "enum": HYPOTHESIS_KEYS},
                },
                "required": ["hypothesis_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_data_quality",
            "description": (
                "Data-quality report for the case: missing values, rows outside the model training "
                "range, sensor consistency flags, which measurements carry a synthetic overlay."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_evidence",
            "description": "Compact list of every evidence item available for citation in this case.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_reference",
            "description": (
                "Short bundled engineering background notes on a topic. Generic, not plant-specific."
            ),
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "enum": REFERENCE_TOPICS}},
                "required": ["topic"],
            },
        },
    },
]
TOOL_NAMES = [t["function"]["name"] for t in TOOL_SPECS]


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    if hasattr(v, "item"):
        try:
            return _clean(v.item())
        except Exception:  # pragma: no cover
            return None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


_SCENARIO_ID = re.compile(r"\s*\bS0\d_[A-Z_]+\b")


def _strip_scenario_ids(v: Any) -> Any:
    """Defence in depth: scenario ids (which name the injected answer) never reach the model."""
    if isinstance(v, str):
        return _SCENARIO_ID.sub("", v)
    if isinstance(v, dict):
        return {k: _strip_scenario_ids(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strip_scenario_ids(x) for x in v]
    return v


def _dump(obj: Any) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return _clean(obj.model_dump())
    if isinstance(obj, dict):
        return _clean(obj)
    return _clean({k: v for k, v in vars(obj).items() if not k.startswith("_")})


def _range(obj: Any) -> tuple[int, int, int]:
    """(source_year, start, end) from a SampleRange-like object."""
    return int(obj.source_year), int(obj.start), int(obj.end)


class ToolRunner:
    def __init__(self, analysis: Any):
        self.analysis = analysis
        self.case_id = analysis.case_id
        scenario = getattr(analysis, "scenario", None)
        self.synthetic = bool(getattr(scenario, "synthetic", False))
        self.scenario_label = "synthetic_overlay" if self.synthetic else "real_only"
        self.synthetic_measurements: list[str] = (
            list(getattr(scenario, "affected_measurements", []) or []) if self.synthetic else []
        )
        self.evidence = list(getattr(analysis, "evidence", []) or [])
        self.evidence_by_id = {e.evidence_id: e for e in self.evidence}
        self.known_evidence_ids: set[str] = set(self.evidence_by_id)

    # ------------------------------------------------------------------
    def run(self, name: str, args: dict | None) -> tuple[dict, list[str]]:
        if name not in TOOL_NAMES:
            raise ToolError(f"unknown tool '{name}'; available: {', '.join(TOOL_NAMES)}")
        args = args or {}
        if not isinstance(args, dict):
            raise ToolError("tool arguments must be a JSON object")
        handler = getattr(self, f"_tool_{name}")
        result, ids = handler(**self._validate_args(name, args))
        return _strip_scenario_ids(result), ids

    def _validate_args(self, name: str, args: dict) -> dict:
        spec = next(t["function"]["parameters"] for t in TOOL_SPECS if t["function"]["name"] == name)
        allowed = set(spec.get("properties", {}))
        extra = set(args) - allowed
        if extra:
            raise ToolError(f"unexpected arguments for {name}: {sorted(extra)}")
        missing = set(spec.get("required", [])) - set(args)
        if missing:
            raise ToolError(f"missing required arguments for {name}: {sorted(missing)}")
        return args

    # ------------------------------------------------------------------
    def _tool_get_sensor_window(self, measurements: Any, start_index: Any, end_index: Any) -> tuple[dict, list[str]]:
        if not isinstance(measurements, list) or not measurements:
            raise ToolError("measurements must be a non-empty list of measurement keys")
        bad = [m for m in measurements if not isinstance(m, str) or m not in MEASUREMENT_KEYS]
        if bad:
            raise ToolError(f"unknown measurements {bad}; allowed: {MEASUREMENT_KEYS}")
        if len(measurements) > MAX_WINDOW_MEASUREMENTS:
            raise ToolError(f"at most {MAX_WINDOW_MEASUREMENTS} measurements per call")
        if isinstance(start_index, bool) or isinstance(end_index, bool) \
                or not isinstance(start_index, int) or not isinstance(end_index, int):
            raise ToolError("start_index and end_index must be integers")
        year, w_start, w_end = _range(self.analysis.window)
        _, r_start, r_end = _range(self.analysis.reference)
        lo, hi = min(r_start, w_start), max(r_end, w_end)
        if start_index < lo or end_index > hi or start_index >= end_index:
            raise ToolError(
                f"range [{start_index},{end_index}) out of bounds; allowed [{lo},{hi}) "
                f"(reference [{r_start},{r_end}), case window [{w_start},{w_end}))"
            )
        frame = self._rows(start_index, end_index)
        in_window = end_index > w_start and start_index < w_end
        result: dict[str, Any] = {
            "source_year": year,
            "rows": {"start": start_index, "end": end_index, "n": int(len(frame))},
            "covers": {
                "reference_rows": int(((frame["row_index"] >= r_start) & (frame["row_index"] < r_end)).sum()),
                "case_window_rows": int(((frame["row_index"] >= w_start) & (frame["row_index"] < w_end)).sum()),
            },
            "time_axis": "ordered hourly samples; no timestamps exist, cite source_year + row_index",
            "scenario_label": self.scenario_label,
            "measurements": {},
        }
        for m in measurements:
            if m not in frame.columns:
                result["measurements"][m] = {"error": "measurement not present in this case"}
                continue
            s = pd.to_numeric(frame[m], errors="coerce")
            synthetic = bool(in_window and m in self.synthetic_measurements)
            vals = s.dropna()
            result["measurements"][m] = {
                "unit": MEASUREMENTS[m]["unit"],
                "n": int(len(s)),
                "missing": int(s.isna().sum()),
                "mean": _clean(float(vals.mean())) if len(vals) else None,
                "median": _clean(float(vals.median())) if len(vals) else None,
                "min": _clean(float(vals.min())) if len(vals) else None,
                "max": _clean(float(vals.max())) if len(vals) else None,
                "std": _clean(float(vals.std())) if len(vals) > 1 else None,
                "first_values": _clean([float(x) for x in vals.head(5)]),
                "last_values": _clean([float(x) for x in vals.tail(5)]),
                "provenance_kind": "measured_plus_synthetic_overlay" if synthetic else "real_observation",
                "synthetic": synthetic,
                "source_year": year,
                "rows": {"start": start_index, "end": end_index},
            }
        ids = [e.evidence_id for e in self.evidence if e.metric in measurements]
        result["related_evidence_ids"] = ids
        return result, ids

    def _rows(self, start: int, end: int) -> pd.DataFrame:
        _, w_start, w_end = _range(self.analysis.window)
        _, r_start, r_end = _range(self.analysis.reference)
        parts = []
        for frame, (fs, fe) in ((self.analysis.reference_frame, (r_start, r_end)),
                                (self.analysis.window_frame, (w_start, w_end))):
            if frame is None or len(frame) == 0:
                continue
            f = frame.reset_index(drop=True)
            if "row_index" not in f.columns:
                f = f.assign(row_index=range(fs, fs + len(f)))
            sel = f[(f["row_index"] >= max(start, fs)) & (f["row_index"] < min(end, fe))]
            parts.append(sel)
        if not parts:
            return pd.DataFrame({"row_index": []})
        out = pd.concat(parts, ignore_index=True)
        return out.drop_duplicates("row_index").sort_values("row_index").reset_index(drop=True)

    def _tool_get_baseline_comparison(self) -> tuple[dict, list[str]]:
        baseline = getattr(self.analysis, "baseline", None)
        model_ev = [e for e in self.evidence if e.kind == "model_derived"]
        ids = [e.evidence_id for e in model_ev]
        if baseline is None:
            return ({"available": False,
                     "note": "no baseline model available for this case; model-derived evidence absent",
                     "evidence_ids": ids, "scenario_label": self.scenario_label,
                     "second_opinion": self._second_opinion()}, ids)
        result = {"available": True, "provenance_kind": "model_derived",
                  "baseline": _dump(baseline), "evidence_ids": ids,
                  "evidence": [self._compact(e) for e in model_ev],
                  "scenario_label": self.scenario_label,
                  "second_opinion": self._second_opinion()}
        return result, ids

    def _second_opinion(self) -> dict:
        """Self-describing GPU challenger block (additive; the production baseline above stays the model of record)."""
        so = getattr(self.analysis, "second_opinion", None)
        if not so:
            return {"available": False,
                    "note": "second_opinion: no independent challenger baseline was run for this case; "
                            "only the production baseline is available"}
        d = _clean(dict(so))
        agreement = d.get("agreement") or "n/a"
        d["note"] = (
            f"second_opinion: an independent GPU-trained MLP baseline ({d.get('model_version')}, challenger, not "
            f"production; holdout MAE {d.get('holdout_mae')} MWh) computed the same TEY residual on the same rows; "
            f"agreement={agreement}. {d.get('agreement_note') or ''} Cite ev_tey_residual_mlp_01 / "
            "ev_model_agreement_01 for these numbers; the production baseline remains the model of record."
        ).strip()
        d["evidence_ids"] = [i for i in ("ev_tey_residual_mlp_01", "ev_model_agreement_01")
                             if i in self.evidence_by_id]
        return d

    def _tool_evaluate_hypothesis(self, hypothesis_key: Any) -> tuple[dict, list[str]]:
        evals = getattr(self.analysis, "hypothesis_evals", None) or {}
        if not isinstance(hypothesis_key, str) or hypothesis_key not in HYPOTHESIS_KEYS:
            raise ToolError(f"hypothesis_key must be one of {HYPOTHESIS_KEYS}")
        ev = evals.get(hypothesis_key)
        if ev is None:
            return ({"hypothesis_key": hypothesis_key, "available": False,
                     "note": "no deterministic evaluation for this hypothesis", "evidence": []}, [])
        d = _dump(ev)
        ids = list(dict.fromkeys(list(d.get("supporting_evidence_ids", [])) +
                                 list(d.get("contradicting_evidence_ids", []))))
        known = [i for i in ids if i in self.evidence_by_id]
        d["available"] = True
        d["note"] = ("deterministic_support_score is a heuristic 0..1 score from fixed rules, "
                     "not a probability and not a confirmation")
        d["evidence"] = [_dump(self.evidence_by_id[i]) for i in known]
        return d, known

    def _tool_get_data_quality(self) -> tuple[dict, list[str]]:
        dq = getattr(self.analysis, "data_quality", None)
        ids = [e.evidence_id for e in self.evidence
               if any(k in e.evidence_id for k in ("ood", "coherence", "consistency", "missing"))
               or any(k in (e.metric or "").lower() for k in ("ood", "coherence", "consistency"))
               or any("out_of_training_range" in f or "isolated" in f for f in (e.flags or []))]
        d = _dump(dq) if dq is not None else {"available": False}
        if isinstance(d.get("notes"), list):
            d["notes"] = [_SCENARIO_ID.sub("", str(n)) for n in d["notes"]]
        d.setdefault("scenario_label", self.scenario_label)
        d.setdefault("synthetic_measurements", self.synthetic_measurements)
        d["scenario_label"] = self.scenario_label
        d["synthetic_measurements"] = list(self.synthetic_measurements)
        d["synthetic_note"] = (
            "synthetic_measurements carry a labelled synthetic overlay applied on top of real rows "
            "for demonstration; the real underlying rows were never mutated"
            if self.synthetic_measurements else "no synthetic overlay; all rows are real observations")
        d["evidence_ids"] = ids
        d["evidence"] = [self._compact(self.evidence_by_id[i]) for i in ids]
        return d, ids

    def _tool_list_evidence(self) -> tuple[dict, list[str]]:
        items = [self._compact(e) for e in self.evidence]
        ids = [e.evidence_id for e in self.evidence]
        return {"count": len(items), "evidence": items, "scenario_label": self.scenario_label}, ids

    def _tool_lookup_reference(self, topic: Any) -> tuple[dict, list[str]]:
        if not isinstance(topic, str) or topic not in REFERENCE_NOTES_KEYS:
            raise ToolError(f"topic must be one of {REFERENCE_TOPICS}")
        note = dict(_REFERENCE_NOTES[topic])
        note["disclaimer"] = ("bundled generic background; no plant manual or OEM document is "
                              "available in this system; do not cite as evidence")
        if not note.get("urls"):
            note["urls"] = []
            note["note"] = "no bundled reference"
        return note, []

    # ------------------------------------------------------------------
    @staticmethod
    def _compact(e: Any) -> dict:
        return _clean({
            "evidence_id": e.evidence_id, "kind": e.kind, "metric": e.metric, "unit": e.unit,
            "title": e.title, "observed_stat": e.observed_stat, "comparison_stat": e.comparison_stat,
            "delta": e.delta, "delta_pct": e.delta_pct, "z_score": e.z_score,
            "data_quality": e.data_quality, "flags": list(e.flags or []),
            "is_synthetic": bool(e.is_synthetic), "method": e.method,
        })


REFERENCE_NOTES_KEYS = set(_REFERENCE_NOTES)
