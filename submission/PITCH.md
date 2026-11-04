# ThermoMind — pitch

## Pitch (≤ 100 words)

ThermoMind is a read-only AI diagnostic investigator for gas-turbine plants. It turns real operating data into an investigation case: deterministic evidence with the computation shown, a reproducible baseline with explicit uncertainty, and a Meta Muse Spark report that may cite only evidence its tool calls returned. A validator rejects fabricated evidence, invented dates and control language; every report is a draft for an engineer. Built during the hackathon window (git history starts 2026-11-04) on public UCI data, it never touches a control system. It helps reliability engineers decide what to investigate first.

## Innovation

- **Evidence-gated reasoning.** The model does not compute; it selects, ranks and explains over server-side evidence. Evidence IDs are a whitelist enforced after generation, so a hallucinated citation is rejected before it reaches a human.
- **Provenance as a first-class type.** `real_observation` / `model_derived` / `synthetic_overlay` travel with every value, and the UI badges them. Synthetic demo scenarios are labelled at every layer.
- **Replayable investigations.** Every model request, tool call, tool result, validation and rewrite is stored and replayable, with latency and token counts.
- **Honest data handling.** No fabricated timestamps, no fabricated labels, no unit laundering (CDP is flagged, TEY stays MWh).

## Who pays

Independent power producers, O&M contractors and utility reliability groups, through a per-plant / per-turbine annual pilot. The champion is the performance or reliability engineer who today triages deviations in spreadsheets beside OEM monitoring and asset-performance software, which we complement rather than replace. Pricing is an output of the first pilots, not an input.

## How Meta is used

`muse-spark-1.3` via `https://api.meta.ai/v1` (OpenAI-compatible chat completions with function tools). The model runs a bounded multi-turn loop over six tools (`get_sensor_window`, `get_baseline_comparison`, `evaluate_hypothesis`, `get_data_quality`, `list_evidence`, `lookup_reference`), then returns a JSON report that is validated, rewritten at most once, or sent to `needs_review`. Because Muse Spark is a reasoning model, the token budget covers reasoning tokens. `meta_used` is true only for real calls; the offline preview is labelled "not a Meta inference".

## Why it is different

OEM monitoring (e.g. Siemens Energy, GE Vernova) and vendor-neutral asset-performance software (e.g. AspenTech) already exist; our hypothesis is that the readable, auditable case, not the alarm, is the unit of value. Incumbent monitoring detects and alerts inside long-term service agreements. ThermoMind produces the thing engineers actually argue over: a transparent, auditable case file with explicit uncertainty and limitations, built on exported data without any OT integration. The unit of value is the case, not the alarm.

## What we do not claim

No accuracy figure, no avoided downtime, no customers, no sales. One plant's 2011–2015 data with no fault labels is the whole evidence base today; the pilot metrics in `docs/MARKET.md` are how we would find out whether this is worth paying for.

## Startup track: path to pilot

1. **Pick one site.** One IPP or O&M contractor with a gas turbine and a performance engineer willing to share a historian export (read-only, offline CSV). No OT integration.
2. **Shadow mode, 8-12 weeks.** Run ThermoMind on the site's own history; engineers review draft cases against their own spreadsheets. Retrain the baseline on that site's data with a chronological split.
3. **Measure.** Case acceptance rate, engineer minutes per triage, false-review rate against the engineers' known events, time to first case after data export (metrics in `docs/MARKET.md`).
4. **Decide on price.** If shadow metrics hold, move to a per-turbine annual pilot, and complete the OT-security assessment in `docs/SAFETY.md` before any live feed.
