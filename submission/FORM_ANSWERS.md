# Form answers (copy-paste)

Meta Global AI Developer Hackathon, Startup track. Every statement is sourced from docs/EVALUATION.md, docs/HACKATHON_WORK.md, docs/FEATURES.md and AGENTS.md.

## Project name
ThermoMind

## Track
Startup

## One-liner (<= 20 words)
A read-only AI investigator that turns gas-turbine data into evidence-cited, human-reviewed cases using Meta Muse Spark tool calls.

## Short description (<= 100 words)
ThermoMind is a read-only decision-support tool for gas-turbine plants. It turns real public operating data into an investigation case: deterministic evidence with the computation shown, a reproducible baseline, and a Meta Muse Spark report that may cite only evidence its tool calls returned. A server-side validator rejects unknown evidence, invented dates and control language, and every report stays a draft for an engineer to review. It never writes to a plant system. Built during the hackathon window on the public UCI gas turbine data set; synthetic scenarios are labelled at every layer.

## Long description (<= 300 words)
Core loop: an engineer opens a case on a window of turbine data. A deterministic evidence engine computes window-vs-reference statistics, baseline residuals and data-quality checks, each with its computation string. Muse Spark (muse-spark-1.3) runs a bounded tool loop over that evidence and drafts a ranked-hypothesis report. A validator checks the report, allows one rewrite, otherwise sends it to needs_review. Every report is draft_requires_human_review.

Real vs synthetic vs simulated: the data are real measurements from an undisclosed Turkish plant (UCI, 2011-2015, 36,733 hourly aggregates, no row-level timestamps, no fault labels). Scenarios S01-S04 are synthetic overlays applied to copies and labelled synthetic. Auxiliaries, thermal screening, the historian replay, CMMS drafts and notifications are simulated.

Plant-ops layer: inbox and personas, "ask the plant" what-if with per-subsystem agents, planner, instrument scorecard, emissions view, shift handover drafts, synthetic grid drill, onboarding brief.

Also: an interactive 3D twin highlighting flagged subsystems on generic geometry; deliberation ("Propose an action") where subsystem agents confer, consensus and dissent are shown, a human decides and nothing is executed; a watchdog on simulated auxiliaries evaluated against an autonomy policy (auto-execution only inside the simulation); and an executive roll-up of stored cases with a drafted brief.

Human in the loop: engineers review, accept or reject; decisions can be reopened. There is no control path: no PLC/SCADA/DCS/historian writes, no setpoints, and the control_system module is a refusal stub. No fault-detection accuracy is claimed.

## How Meta models are used
Model: muse-spark-1.3 via https://api.meta.ai/v1 (OpenAI-compatible chat completions with function tools); the key is server-side only.
- Investigation: a bounded multi-turn tool loop over six tools (get_sensor_window, get_baseline_comparison, evaluate_hypothesis, get_data_quality, list_evidence, lookup_reference), plus recall_similar_cases from reviewed precedents.
- Subsystem what-if agents (intake, compressor, combustion turbine, exhaust/emissions) plus an aggregator.
- Deliberation agents that confer on a proposed action.
- Drafts: shift handover, onboarding brief, executive brief, grid-drill operator brief.
- All outputs are validated server-side (evidence-ID whitelist, no fabricated dates, no control language); one rewrite, then a labelled fallback. meta_used is true only for real API calls; the offline preview is labelled "not a Meta inference".

## What was built during the hackathon
Git history starts 2026-11-04 18:15 UTC (restarted from an empty directory); 56+ commits; all code written in the window (docs/HACKATHON_WORK.md). Areas: API contract and schemas; UCI data layer and upload validator; HistGradientBoosting baseline with chronological split and an optional GPU MLP challenger; synthetic scenario generator; evidence engine; Muse Spark agent, tools and report validator; FastAPI + SQLite case store with replayable event traces; React/TypeScript web app; plant-ops features (inbox, what-if, planner, instruments, emissions, thermal simulation, grid drill, handover, simulated connectors); deliberation, watchdog, executive view, autonomy policy, onboarding, 3D twin, agent tree; scripts, Docker, CI, tests, docs.

## Team
`<FILL by owner>`

## Repository URL
https://github.com/manvendersingh21/thermomind

## Demo video
`<YouTube link — upload submission/video/thermomind_demo.mp4>`

## Live demo
Not deployed; reproducible locally (README).

## Measured results (from docs/EVALUATION.md)
- Baseline (HistGradientBoosting, TEY in MWh), 2015 holdout never used for fitting or thresholds: MAE 1.293 MWh, R-squared 0.9896. Naive train-mean MAE 12.957 MWh; naive previous-observation MAE 4.125 MWh.
- Four live Muse Spark investigations (S01-S04) ran through the full pipeline against api.meta.ai; the S04 case was accepted first pass with zero validation errors, and the others were accepted first pass.
- Tests: 531 backend tests passed; 52 web tests passed; typecheck clean.
- These show the features carry information about TEY. They do not show fault detection.

## Known limits
- One plant's public Turkish data, 2011-2015; no row-level timestamps; generalisation to other turbines, plants or years is not evaluated.
- No verified fault labels; faults in scenarios are synthetic overlays, not real events.
- Auxiliaries, thermal screening, historian replay, CMMS and notifications are simulated; 3D twin and animation use generic geometry, not the real facility.
- Muse Spark report correctness has no ground truth; the validator checks provenance and form only.
- No physics simulator exists in this repository (a design was started but not built).
- No pilot, users, revenue, accuracy, savings or avoided-downtime claims.
