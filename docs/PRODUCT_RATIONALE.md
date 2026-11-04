# Product rationale: the operator-side case

Written for a plant head. Everything below is a hypothesis to validate in a pilot, not a result. ThermoMind is a hackathon prototype, read-only, built on public UCI data and labelled synthetic scenarios. No savings, accuracy or adoption is claimed.

## 1. Where gas-turbine O&M loses time and takes risk

| Problem | Who feels it | Cost, in kind | Where the risk sits |
|---|---|---|---|
| Alarm floods and nuisance alarms | Control-room operators, shift supervisor | Hours of triage per shift; real alarms get buried | A genuine early warning is dismissed with the noise |
| Slow, undocumented deviation investigations | Performance engineer | Days of spreadsheet work; the reasoning lives in one head | Same question re-investigated; weak audit trail |
| Instrument drift causing false trips and call-outs | I&C technician, operations | Unnecessary call-outs, occasional derate or trip | A bad sensor mistaken for a machine fault, or the reverse |
| When to wash the compressor or change inlet filters | Performance engineer, plant manager | Output and heat-rate loss if late; lost run time if early | Forced outage instead of planned outage |
| Emissions excursions caught late | Environmental / compliance lead | Reporting effort, possible derate | Permit exposure |
| Cross-department blind spots | I&C, performance, operations | Tests or changes that disturb someone else's numbers | A calibration or test invalidates a performance baseline unnoticed |
| Shift handover knowledge loss | Incoming shift | Re-discovery time | Open issues dropped |
| CMMS work orders written from memory | Maintenance planner, technician | Rework, vague tickets | Weak failure history for later decisions |

## 2. What ThermoMind does today, and what stays human

| Problem | Built today | Stays human |
|---|---|---|
| Slow investigations | Evidence-first investigation: deterministic evidence engine computes every number; Muse Spark must call tools and may cite only evidence IDs they returned; validator rejects fabricated evidence, dates and control language; replayable trace | Accept, reject or ask for more data |
| Reasoning quality | GPU second-opinion baseline (PyTorch challenger on the same split); precedent recall of previously reviewed cases | Judging whether a precedent applies |
| Alarm noise, drift | Instrument health scorecard to screen a suspect sensor before anyone is called out; emissions watch | Calibration, inspection, any reporting |
| Wash / filter timing | Maintenance planner: break-even for wash or filter change-out using the user's own cost and loss assumptions | The decision and the schedule |
| Cross-department blind spots | "Ask the plant": multi-agent what-if with cross-impact and recommended checks; routing of work requests to the responsible engineer and supervisor (notifications are simulated) | Whether to proceed; every sign-off |
| Handover, CMMS | Shift handover draft; CMMS draft export | Reviewing and filing both |
| Trust and training | Synthetic scenarios (labelled `synthetic=true`) to rehearse the workflow; pilot metrics view | Deciding what counts as success |

ThermoMind has no write path to any PLC, SCADA, DCS or historian. Every report is `draft_requires_human_review`. Every action, control and sign-off is a person's.

## 3. How it could reduce downtime and risk (hypotheses, with the pilot metric)

- **Fewer unnecessary call-outs.** Screening instruments first separates "sensor" from "machine". Metric: call-outs later traced to a sensor, before vs after, on comparable periods.
- **Earlier, better-documented decisions.** The case file shows evidence and uncertainty up front. Metric: engineer time per case; reviewer acceptance and rejection rates.
- **Planned, not forced, outages.** Wash and filter break-even makes the timing argument explicit. Metric: share of washes and change-outs done as planned work versus forced.
- **Cross-impact awareness before a test.** A what-if surfaces who is affected. Metric: count of tests or changes later found to have disturbed another team's numbers.
- **Auditability.** Every number has a computation and every model step is stored. Metric: time to reconstruct why a decision was made.
- **Normal windows stay quiet.** Metric: false-review rate on known-normal windows. We have only a small control set so far, not a false-alarm study.

## 4. What changes for each person

- **Technician.** Opens a work request that already names the suspect sensor and the evidence, instead of a vague ticket; the CMMS draft is pre-filled for review.
- **I&C engineer.** Sees the instrument scorecard and, before a calibration, a note of which performance numbers the change touches.
- **Performance engineer.** Starts from an evidence list with computations, not a blank spreadsheet; recalls reviewed precedents; checks the model's claims against the trace.
- **Shift supervisor.** Gets a handover draft and routed requests with a named owner; the simulated notification shows the intended flow.
- **Plant manager.** Gets a break-even view for wash and filter timing, and a pilot metrics page to judge the tool on the plant's own cases.

## 5. Why a company might pay, and why not

**For.** The case file is the unit of value: a reviewable record of what was checked and why. It is vendor-neutral and works on exported data, so it starts without an OT integration project. It is auditable by design. Setup is fast: an export and a column mapping.

**Against, honestly.** Incumbents (Siemens Energy, GE Vernova, AspenTech) are embedded in service agreements and own the live data. OT security and IT review take time even for a read-only tool. OEM contracts may restrict sharing turbine data with third parties or model providers. We have one public data set from one plant, no fault labels, no customers, and no evidence yet that engineers prefer this over their current routine. Several features run on assumptions the user supplies, and routing is simulated.

## 6. What we will not build

- No autonomous control, setpoints, trip or start commands, or any write to plant systems.
- No "AI operator" and no auto-executed work orders; drafts only.
- No alarm replacement or safety function; severity is review priority.
- No unverified claims: no invented savings, dates, fault labels or accuracy figures.

A pilot with agreed success criteria on a site's own historical cases is the next step that would tell us whether any of this is worth paying for.
