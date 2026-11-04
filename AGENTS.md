# AGENTS.md — rules for every agent working on ThermoMind

Read `contracts/api.md` and `apps/api/app/schemas.py` first. They are the contract.

## Non-negotiables
1. Read-only decision support. No PLC/SCADA/DCS/historian writes, no setpoints, no control commands, ever. Reports are always `draft_requires_human_review`.
2. Honest provenance. UCI data = real measurements from an undisclosed Turkish plant, 2011–2015, 36,733 hourly aggregates, **no row-level timestamps** (keep `source_year` + `row_index`; never fabricate dates). No verified fault labels exist. TEY is MWh as published; do not convert to MW. CDP unit "mbar" is as published and flagged as under validation.
3. Synthetic scenarios are labelled `synthetic=true` at every layer. Original rows are never mutated.
4. Never invent test results, metrics, API responses, or plant failures. Metrics come from running code.
5. Meta Muse Spark (`muse-spark-1.3` via `https://api.meta.ai/v1`, OpenAI-compatible) must do substantive work via tools. Key is `MODEL_API_KEY` (alias `MUSE_API_KEY`) in `.env`, server-side only; never log or return it.
6. Smaller tested feature > bigger broken one.

## Working rules
- Own only your assigned tree. Shared files (`schemas.py`, `config.py`, `contracts/`) are changed only by the principal.
- Python: `. .venv/bin/activate` from repo root; run tests with `cd apps/api && python -m pytest -q`.
- Do NOT run `git commit`; the principal commits. Do not create branches.
- Return: files changed, commands run, real test output, blockers, integration notes.
- Keep secrets out of logs. Keep UI copy honest (REAL PUBLIC DATA / MODEL-DERIVED / SYNTHETIC OVERLAY / HUMAN REVIEW REQUIRED).
