# Market and business hypothesis (Startup Track)

This document states hypotheses to be validated. Nothing here is a result.

## Who has the problem

Gas-turbine fleets are run by people who must decide, every week, which performance deviations deserve an investigation. The decision is made by a small number of **performance / reliability engineers** per fleet, typically with spreadsheets, historian trend screens and OEM monitoring reports that flag but rarely explain.

| Role | Hypothesised need |
|---|---|
| **Buyer:** independent power producers (IPPs), O&M contractors, plant reliability groups within utilities | Fewer hours per investigation, defensible prioritisation, an audit trail for what was checked and why |
| **Champion:** performance / reliability engineer | A case file that shows the evidence and the computation, states uncertainty, and can be accepted or rejected in minutes |
| **Gatekeepers:** plant IT / OT security, OEM relationship owners | No connection to control systems, exported data only, clear data-governance story |

## The wedge

Incumbent monitoring from **Siemens Energy, GE Vernova and AspenTech** (and OEM remote monitoring centres) is OEM-integrated and embedded in long-term service agreements. We do not compete with it and do not dismiss it. ThermoMind sits *beside* those systems:

- works on **exported data** (CSV / historian extract) rather than live integration, so it can start without an OT project;
- produces a **transparent, auditable investigation case**: every number traceable to a computation, every hypothesis tied to evidence IDs, explicit limitations and "what would change the assessment";
- treats the AI model as a reasoning layer over deterministic evidence, not as an oracle, which is what sceptical engineers and their managers ask for.

The hypothesis is that the *case file* (not the detection) is the unit of value, and that no incumbent sells one that an engineer can read end to end in five minutes.

## Business model hypothesis

Pilot pricing per plant (or per turbine) per year, starting with a fixed-scope pilot: a defined fleet, a defined set of historical cases, success criteria agreed up front. Expansion is by additional turbines and by moving from exported data to scheduled extracts. Pricing numbers are deliberately not stated; they are an output of the first pilots.

## Metrics to validate in a pilot

| Metric | How measured |
|---|---|
| Engineer time per investigation case | Timed before/after on comparable cases |
| Evidence-link correctness | Share of cited evidence IDs an engineer judges relevant and correctly computed |
| False-alarm behaviour | How often normal windows (like S01) produce `review`/`urgent_review`; reviewer rejection rate |
| Analyst acceptance | Share of cases `accepted` vs `rejected` vs `more_data_requested`, with comments |
| Deployment time | Hours from data export to first reviewed case; number of IT/OT approvals needed |

## Risks and open questions

- **Data.** The only data set used is one Turkish plant, 2011–2015, with no fault labels and no load signal. Everything about transfer to other machines is unknown.
- **Confounding.** Dispatch changes look like performance changes; without a load signal the baseline cannot separate them.
- **Units and semantics.** The CDP unit is already under question; real plants have hundreds of tags with site-specific names and units.
- **OT security and procurement.** Even a read-only tool needs an OT security review and a data-governance agreement; utility sales cycles are long and often run through the OEM or the O&M contractor.
- **Vendor access.** OEM contracts may restrict how turbine data is shared with third parties or model providers.
- **Model dependency.** Report quality depends on the hosted model; version pinning and regression suites are required.
- **Liability.** The tool must stay advisory; any drift toward alarms or recommendations changes the regulatory and insurance picture.

## What the CEO buys

Hypotheses, not results; each is a pilot metric.

- **Forced-outage risk, reduced by earlier decisions.** Deviations, instrument doubts and wash or filter timing reach a named owner with evidence attached. Metric: planned versus forced maintenance share.
- **Decision speed with an audit trail.** Every figure carries its computation; every AI draft is validated and signed by a person. Metric: engineer time per case; time to reconstruct a decision for a regulator or insurer.
- **Compliance exposure seen early.** Emissions screening and excursions are counted per year. Metric: excursions found by screening before routine reporting.
- **Knowledge retention.** Reviewed precedents, handover drafts and onboarding briefs accumulate as staff change. Metric: precedents reused per new case.
- **Vendor independence and OT safety.** Exported data only; no control-system write path. Metric: approvals and hours from export to first case.

The `/executive` page shows these as prototype metrics with provenance. No savings, availability gain or revenue is claimed; the data is one public plant without timestamps, and the thermal and grid figures are simulated or assumption-based.

## What we are not claiming

No avoided downtime, no accuracy figure, no adoption, no sales, no letters of intent. The claim is narrower: a transparent investigation case built on real public data and real tool-using inference is possible today, and the pilot metrics above would tell us whether it is worth paying for.

## Incumbent reference (for context, not comparison claims)

- Siemens Energy combined-cycle plant portfolio (gas and steam turbines for EPC projects): https://www.siemensenergy.com/global/en/home/products-services/product/combined-cycle-power-plants.html — an example of the OEM scope ThermoMind would sit beside, not replace. OEM monitoring and performance services ship with the equipment; our wedge is a vendor-neutral, auditable investigation layer over exported data.

## Feature map (built today)

Mapped to [PRODUCT_RATIONALE.md](PRODUCT_RATIONALE.md): evidence-first investigation, GPU second-opinion baseline, precedent recall, instrument health scorecard, emissions watch, maintenance planner (user assumptions), "Ask the plant" cross-impact what-if, work-request routing (simulated notifications), shift handover draft, CMMS draft export, synthetic scenario training, pilot metrics. All read-only and draft-only; none is validated on a second plant.
