# Hard questions, honest answers

Numbers cite [EVALUATION.md](EVALUATION.md). Nothing here is a validation claim.

**1. The data is from one Turkish plant, 2011-2015. Why should anyone care?**
It is an open, real, multi-year gas-turbine data set. We treat it as a development corpus, not as proof the approach generalises. Nothing is validated on another turbine; a pilot on a site's own data is the next step.

**2. There are no fault labels. What do you actually evaluate?**
Only the baseline's prediction of TEY (2015 holdout MAE 1.293 MWh, R² 0.9896, versus 12.957 and 4.125 for naive baselines) and that the evidence engine behaves as designed on scenarios (0 of 4 real-only windows flagged; this is a single control window per case, not a false-alarm study). That shows the features carry information, not that faults are detected. We do not claim detection accuracy.

**3. The faults are synthetic. Isn't that circular?**
Partly, yes. The overlays are seeded, labelled `synthetic=true` at every layer, and written by us, so the deterministic engine finding them is a plumbing test, not evidence of real-world skill. They exist so the demo can exercise the pipeline when real labels do not exist.

**4. Is the LLM decorative?**
The model chooses which tools to call, interprets their results, ranks hypotheses and writes the report. In the four recorded live runs (S01-S04) it made 9-11 tool calls each over 3-4 turns. It does not compute numbers; the server does. Whether its reasoning is better than the deterministic ranking is not benchmarked, and we say so.

**5. How do you prevent hallucinated evidence?**
Every number in the evidence list is produced server-side with its computation string. After generation, the validator whitelists evidence IDs against what the tools returned this case, checks schema, case id, dates and control language, allows one rewrite, otherwise marks `needs_review`. It guarantees provenance and form, not that the reasoning is correct.

**6. Siemens, GE and AspenTech already do monitoring. Why you?**
They detect and alert inside service agreements and need OT integration. We produce an auditable case file from exported data, with no integration, and complement them. We have no customers and no evidence yet that engineers prefer this; the pilot would test it.

**7. What does the GPU do?**
It trains an optional PyTorch MLP challenger, benchmarked on the same chronological split and metric definitions as the production model and reported on the Evaluation page. Numbers (`data/models/mlp_v1.json`): MAE on 2014 validation 1.113 (MLP) vs 1.364 (HGBR); on the untouched 2015 holdout 1.664 (MLP) vs 1.293 (HGBR). The MLP wins on validation and loses on holdout; HGBR retained as the production baseline. Any selection would be on the validation year only; we make no accuracy claim from the challenger and the holdout is never used for selection.

**8. Is it safe near a power plant?**
It has no write path to any PLC, SCADA, DCS or historian, issues no setpoints, and the validator rejects control instructions. Reports are drafts requiring human review; severity ranks review priority, not alarms. It is a single-user prototype with no auth and is not hardened for an OT network (docs/SAFETY.md).

**9. What happens when Meta is down?**
The pipeline reports the failure; an offline preview mode using the deterministic engine can run, and it is labelled "not a Meta inference" with `meta_used=false`. Stored live cases remain replayable. Nothing silently pretends to be a Meta call.

**10. What is the business model?**
Per-turbine or per-plant annual pilot for IPPs, O&M contractors and utility reliability groups. Price is an output of pilots, not an input. No revenue, customers or LOIs today (docs/MARKET.md).

**11. What is the next pilot?**
One site, historian CSV export, 8-12 weeks shadow mode, measuring acceptance rate, engineer minutes per triage and false-review rate (submission/PITCH.md).

**12. What is NOT built?**
Auth and multi-tenancy; live historian connectors; per-site retraining workflow; fault-labelled validation; a benchmark of Muse Spark report correctness; false-alarm study; deployment (local demo only; Docker image not tested; no live public deployment); any OT-security assessment. The model is statistical, not thermodynamic, and residuals are confounded by dispatch changes.
