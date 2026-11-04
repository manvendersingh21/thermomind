# ThermoMind — pitch

## Pitch (≤ 100 words)

ThermoMind is a read-only AI diagnostic investigator for gas-turbine plants. It turns real operating data into an investigation case: deterministic evidence with the computation shown, a reproducible baseline with explicit uncertainty, and a Meta Muse Spark report that may cite only evidence its tool calls returned. A validator rejects fabricated evidence, invented dates and control language; every report is a draft for an engineer. Built during the hackathon window (git history starts 2026-11-04) on public UCI data, it never touches a control system. It helps reliability engineers decide what to investigate first.

## Innovation

- **Evidence-gated reasoning.** The model does not compute; it selects, ranks and explains over server-side evidence. Evidence IDs are a whitelist enforced after generation, so a hallucinated citation is rejected before it reaches a human.
- **Provenance as a first-class type.** `real_observation` / `model_derived` / `synthetic_overlay` travel with every value, and the UI badges them. Synthetic demo scenarios are labelled at every layer.
- **Replayable investigations.** Every model request, tool call, tool result, validation and rewrite is stored and replayable, with latency and token counts.
- **Honest data handling.** No fabricated timestamps, no fabricated labels, no unit laundering (CDP is flagged, TEY stays MWh).

## Who pays

The buyer is the CEO (or COO) of a generation company, IPP or O&M contractor; the champion is the reliability or performance engineer. What the CEO would be buying, each a hypothesis for a pilot with a named metric, not a result:

- **Fewer forced outages through earlier, better-documented decisions.** Metric: share of washes, filter change-outs and repairs done as planned work versus forced, before vs after.
- **Faster investigations.** Metric: engineer time per case on comparable deviations; time from data export to a reviewed case.
- **An audit trail regulators and insurers can read.** Every number has a computation and every model step is stored. Metric: time to reconstruct why a decision was made.
- **Knowledge that stays when people retire.** Reviewed precedents, handover drafts and onboarding briefs. Metric: precedents reused per new case; time for a new engineer to close a first case.
- **Vendor independence.** Works on exported data beside OEM monitoring. Metric: hours and approvals from export to first case.

The `/executive` view shows these as prototype metrics with provenance. Pricing is per plant / per turbine per year and is an output of the first pilots, not an input.

## How Meta is used

`muse-spark-1.3` via `https://api.meta.ai/v1` (OpenAI-compatible chat completions with function tools). The model runs a bounded multi-turn loop over six tools (`get_sensor_window`, `get_baseline_comparison`, `evaluate_hypothesis`, `get_data_quality`, `list_evidence`, `lookup_reference`), then returns a JSON report that is validated, rewritten at most once, or sent to `needs_review`. Because Muse Spark is a reasoning model, the token budget covers reasoning tokens. `meta_used` is true only for real calls; the offline preview is labelled "not a Meta inference".

## Why it is different

OEM monitoring (e.g. Siemens Energy, GE Vernova) and vendor-neutral asset-performance software (e.g. AspenTech) already detect and alert, mostly inside long-term service agreements. ThermoMind does not compete on detection. It produces what a CEO, a regulator or an insurer can actually read: a case file where every number has its computation, every AI claim cites evidence a tool returned, uncertainty and limitations are explicit, and a named person signs the decision. It runs on exported data with no write path to any control system, so it starts without an OT project and leaves the plant owner, not a vendor, holding the record. The hypothesis is that the auditable case, not the alarm, is the unit of value.

## Ambition

To become for agentic plant operations what Schneider Electric is for electrical infrastructure: agents in the picture across every subsystem, humans in control of your power. ThermoMind is an independent project with no affiliation to Schneider Electric or any OEM; the comparison is about scale of ambition, not a claim of parity.

## What we do not claim

No accuracy figure, no avoided downtime, no customers, no sales. One plant's 2011–2015 data with no fault labels is the whole evidence base today; the pilot metrics in `docs/MARKET.md` are how we would find out whether this is worth paying for.

## Startup track: path to pilot

1. **Pick one site.** One IPP or O&M contractor with a gas turbine and a performance engineer willing to share a historian export (read-only, offline CSV). No OT integration.
2. **Shadow mode, 8-12 weeks.** Run ThermoMind on the site's own history; engineers review draft cases against their own spreadsheets. Retrain the baseline on that site's data with a chronological split.
3. **Measure.** Case acceptance rate, engineer minutes per triage, false-review rate against the engineers' known events, time to first case after data export (metrics in `docs/MARKET.md`).
4. **Decide on price.** If shadow metrics hold, move to a per-turbine annual pilot, and complete the OT-security assessment in `docs/SAFETY.md` before any live feed.
