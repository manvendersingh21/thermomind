# Submission

**Event:** Meta Global AI Developer Hackathon (https://dev.meta.ai/events/global-hackathon, https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
**Track:** STARTUP
**Deadline:** 4 November 2026, 9 PM ET (event window 26 October – 4 November 2026)

## Fields to fill

| Field | Value |
|---|---|
| Project name | ThermoMind |
| One-liner | ThermoMind is a read-only AI diagnostic investigator for gas-turbine power generation. It combines authentic operating measurements, reproducible anomaly analysis, Meta Muse Spark reasoning with real tool use, and inspectable evidence to help plant engineers prioritize investigations. |
| Repository URL | https://github.com/manvendersingh21/thermomind |
| Demo video URL | `<FILL after upload: submission/video/thermomind_demo.mp4>` (to be filled by the owner at submission) |
| Live demo URL (optional) | not deployed (local reproducible demo; optional quick tunnel command in docs/DEPLOY.md) |
| Team | `<FILL: names, roles, contact email>` (to be filled by the owner at submission) |
| Meta model used | `muse-spark-1.3` via `https://api.meta.ai/v1` (OpenAI-compatible chat completions with function tools) |
| Meta usage summary | Model runs a bounded multi-turn tool loop over six server-side tools and drafts a validated investigation report; `meta_used=true` only for real API calls; offline preview is labelled "not a Meta inference" |
| Data | UCI Gas Turbine CO and NOx Emission Data Set (ID 551, DOI 10.24432/C5WC95, CC BY 4.0; Kaya, Tüfekci & Gürgen 2019) |
| Licence | MIT (repository); CC BY 4.0 (data). The Overview and case pages embed the 'Combined Cycle Power Plant' interactive animation by educational-animation.org (https://www.educational-animation.org/en/combined-cycle-power-plant/; educational-animation.org — animation code MIT; text and graphics CC BY 4.0). It is a generic educational plant, not the UCI facility. |
| Built during the event | Yes. The repository's git history begins 2026-11-04 18:15 UTC; the project was restarted from an empty directory that day after earlier work became inaccessible. All code in this repository was written during the hackathon window. (docs/HACKATHON_WORK.md) |

## Checklist

- [ ] `make setup && make data && make train` succeed on a clean clone
- [ ] `cd apps/api && python -m pytest -q` passes (paste output into docs/EVALUATION.md)
- [ ] `cd apps/web && npm run typecheck && npm run build` pass
- [ ] `make meta-smoke` run once; record ts, model id, latency, tool calls, validator result in docs/EVALUATION.md
- [ ] At least one stored `meta_live` investigation per scenario S01–S04 (via `make seed` or the UI)
- [ ] docs/EVALUATION.md metrics table filled from `data/models/baseline_v1.json` (no typed numbers)
- [ ] Screenshots added at `docs/screenshots/{home,data,investigation,evaluation,replay}.png`
- [ ] README status banner still accurate; no claim of accuracy, adoption, avoided downtime or sales anywhere
- [ ] `.env` not committed; `git grep -i "sk-"` and a search for the key value return nothing
- [ ] Docker image builds (`docker build -t thermomind .`) on a machine with Docker, or note that it was not tested
- [ ] Demo video recorded following docs/DEMO_SCRIPT.md; synthetic overlays and offline preview labelled on screen
- [ ] submission/PITCH.md ≤ 100-word pitch pasted into the form
- [ ] Repository URL, video URL, team fields above filled (to be filled by the owner at submission); form submitted before 9 PM ET

## Judging notes we want the reader to see first

1. Real data with honest provenance (no timestamps, no labels, CDP unit flagged).
2. Muse Spark doing work through tools, with a trace that can be replayed.
3. A validator that blocks hallucinated evidence and control language server-side (exact whitelist for evidence ids; pattern-based for control language).
4. Read-only by architecture; human review by contract.
5. A startup thesis with named incumbents, a narrow wedge, and metrics a pilot would have to measure.

## Submission form answers (copy-paste)

**Project name:** ThermoMind

**Track:** Startup

**One-liner:** A read-only AI diagnostic investigator for gas-turbine power plants: real measurements, reproducible evidence, and a Meta Muse Spark report that can only cite evidence its tools returned.

**Description (100 words):** ThermoMind turns real gas-turbine operating data into an investigation case for plant engineers. A deterministic engine computes evidence and a baseline expected-output comparison. Meta's Muse Spark then investigates through function tools, ranks hypotheses, and drafts a report. A validator rejects fabricated evidence IDs, invented dates and control instructions, so every report is a draft requiring human review. Data is the public UCI Turkish gas-turbine set (no timestamps, no fault labels); demo faults are labelled synthetic overlays. Every model request and tool call is stored and replayable. ThermoMind is strictly read-only and never touches a control system. It was built during the hackathon window.

**Meta model / API used and how:** `muse-spark-1.3` via `https://api.meta.ai/v1` (OpenAI-compatible chat completions) with function tools: `get_sensor_window`, `get_baseline_comparison`, `evaluate_hypothesis`, `get_data_quality`, `list_evidence`, `lookup_reference`. The model runs a bounded multi-turn tool loop (3-4 turns, 9-11 tool calls in the three recorded live runs), then returns a JSON report that is validated (evidence-ID whitelist, schema, dates, control language), rewritten at most once, or sent to needs_review. Record: docs/EVALUATION.md.

**What was built during the hackathon:** Everything in this repository, written during the hackathon window from an empty directory (git history begins 2026-11-04; docs/HACKATHON_WORK.md): data layer, HGBR baseline with chronological split, synthetic scenarios, evidence engine, Muse Spark orchestrator and validator, FastAPI + SQLite, React UI with replay, optional PyTorch challenger, 140 passing tests.

**Team:** `<FILL: names, roles, contact email>`

**Links:** Repo `<FILL: pending push>`; video `<FILL after upload>`; live URL: none (local demo); docs: README.md, docs/EVALUATION.md, docs/FAQ_JUDGES.md.

## Still to fill by hand

Repository URL, video URL, team, test/typecheck output in docs/EVALUATION.md (Test suite section is a placeholder there), any S04 live case if wanted.

## Not built / not tested

Docker image not tested; no live public deployment.
