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

Real vs synthetic vs simulated: the data are real measurements from an undisclosed Turkish plant (UCI, 2011-2015, 36,733 hourly aggregates, no row-level timestamps, no fault labels). Scenarios S02-S04 are synthetic overlays applied to copies and labelled synthetic; S01 is real rows only. Auxiliaries, thermal screening, the historian replay, CMMS drafts and notifications are simulated.

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
Git history starts 2026-11-04 18:15 UTC (restarted from an empty directory); 60+ commits; all code written in the window (docs/HACKATHON_WORK.md). Areas: API contract and schemas; UCI data layer and upload validator; HistGradientBoosting baseline with chronological split and an optional GPU MLP challenger; synthetic scenario generator; evidence engine; Muse Spark agent, tools and report validator; FastAPI + SQLite case store with replayable event traces; React/TypeScript web app; plant-ops features (inbox, what-if, planner, instruments, emissions, thermal simulation, grid drill, handover, simulated connectors); deliberation, watchdog, executive view, autonomy policy, onboarding, 3D twin, agent tree; scripts, Docker, CI, tests, docs.

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
- Four live Muse Spark investigations (S01-S04) ran through the full pipeline against api.meta.ai (9-11 tool calls each); all four were accepted by the validator on the first pass. Report correctness is not benchmarked.
- Tests: 531 backend tests passed; 52 web tests passed; typecheck clean.
- These show the features carry information about TEY. They do not show fault detection.

## Known limits
- One plant's public Turkish data, 2011-2015; no row-level timestamps; generalisation to other turbines, plants or years is not evaluated.
- No verified fault labels; faults in scenarios are synthetic overlays, not real events.
- Auxiliaries, thermal screening, historian replay, CMMS and notifications are simulated; 3D twin and animation use generic geometry, not the real facility.
- Muse Spark report correctness has no ground truth; the validator checks provenance and form only.
- The 0-D gas-turbine physics simulator (`/simulator`) is experimental and was finished in the last hour: 9 tests, calibrated to UCI steady states (per-channel MAE in docs/SIMULATOR.md); it is a simulation, not a digital twin of any facility.
- No pilot, users, revenue, accuracy, savings or avoided-downtime claims.

## Push the Frontier — how Meta's models meet a physical system here

ThermoMind uses Meta Muse Spark to understand and reason about a physical system, a gas-turbine power plant, with the model held to verifiable tools rather than free text:

- **Understand**: real turbine measurements (36,733 hourly rows) plus a measured-data baseline model; Muse Spark investigates deviations by calling deterministic evidence tools and must cite only evidence ids those tools returned. Four live runs, zero validation errors.
- **Control-adjacent, with humans in the loop**: subsystem agents confer before any physical action ("Propose an action"), a watchdog notices needs and routes them to the responsible engineer, and an explicit autonomy policy says what agents may do alone (triage, drafts, routing) and what only humans may do (anything that touches the plant). The software has no write path to a control system by design; the route to action is a human-approved plan.
- **Simulate**: a first-principles 0-D gas-turbine physics simulator (Brayton cycle, governor, injectable faults) calibrated to the real data lets the agents and the engineers rehearse faults and responses on a model, with a live animated diagram and a 3D twin.
- **New capability for the machine**: turning raw plant telemetry into an auditable, evidence-linked investigation and a cross-team decision record in minutes, instead of days of manual work.

This is a prototype on public data. Accuracy, savings and plant deployment are not claimed; the pilot path and metrics are in docs/MARKET.md.

## Answers framed to the review criteria

### 1. Project idea (clarity · feasibility · theme fit: Push the Frontier)
**Idea in one sentence.** ThermoMind turns a gas-turbine plant's raw measurements into evidence-linked investigations and cross-team decisions, with Meta Muse Spark reasoning over a physical system through verifiable tools, and humans deciding anything that touches the plant.
**Why it fits "Push the Frontier".** It gives a physical system a new capability: the plant's own data becomes an auditable case file in minutes; subsystem agents confer about the domino effect before a physical action; a watchdog notices needs on its own; a physics simulator calibrated to the real data lets teams rehearse faults; an explicit autonomy policy states what agents may do alone. Energy is the domain; understanding and (human-gated) control of a physical system is the frontier.
**Feasibility, demonstrated.** Built and running on public data (UCI dataset 551, 36,733 hourly rows): four live Muse Spark investigations stored with zero validator errors; baseline model holdout MAE 1.293 MWh (naive 12.957 / 4.125); 540 backend tests and 52 web tests green; reproducible from a clean clone with four make targets. Pilot path: read-only historian export from one consenting plant, then prospective cases and work-order verification.

### 2. Technical skill (what we built · techniques used)
- **Agentic reasoning with verifiable tools.** Muse Spark runs a bounded tool loop (get_sensor_window, get_baseline_comparison, evaluate_hypothesis, get_data_quality, list_evidence, lookup_reference, recall_similar_cases); a server-side validator rejects any report that cites evidence ids the tools did not return, fabricated dates, or control language (including grid/electrical vocabulary), with one bounded rewrite and a labelled fallback.
- **Multi-agent deliberation.** Parallel subsystem agents (intake, compressor, combustion/turbine, exhaust/emissions, generator) plus a constraints agent and an aggregator produce consensus, dissent and a go/no-go recommendation; a human decision is recorded and routed; nothing is executed.
- **Measured-data baseline + GPU challenger.** HistGradientBoosting on a chronological split (train 2011–13, validate 2014, holdout 2015) with naive baselines; a PyTorch MLP trained on a V100 as a second opinion, reported honestly (it loses on holdout).
- **Deterministic evidence engine.** Window-vs-reference statistics, robust spike segments, coherence checks, out-of-training-range flags, immutable evidence ids with the computation string.
- **Physics simulation.** 0-D Brayton-cycle gas turbine (cp(T) gas properties, compressor map, combustor energy balance, turbine expansion, swing equation with droop+PI governor, RK4), calibrated by least squares to the plant's steady states, injectable physical and instrument faults, SSE streaming, live animated diagram, investigation on simulated windows labelled SIMULATED_PLANT.
- **Electrical and grid models.** IEEE C57.91-style transformer hot-spot and ageing, I²-based conductor rise, inertia/reactive readiness, contingency options on a simulated topology, synthetic grid-event drills.
- **Product engineering.** FastAPI + SQLite backend with 27 documented mutating routes and a red-team suite (key leakage, upload traversal, formula injection, fuzzing with NaN/inf), React/TypeScript/Vite UI with a three.js digital twin and the verified postMessage protocol of a third-party 3D viewer, Playwright e2e, accessibility fixes, CI workflow, Docker file.
- **Process.** Built on 4 Nov 2026 by a principal AI agent coordinating a tree of specialist agents with contracts first, file ownership, adversarial reviews and continuous integration; every number in the docs comes from running the code.
