# Submission

**Event:** Meta Global AI Developer Hackathon (https://dev.meta.ai/events/global-hackathon, https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
**Track:** STARTUP
**Deadline:** 4 November 2026, 9 PM ET (event window 26 October – 4 November 2026)

## Fields to fill

| Field | Value |
|---|---|
| Project name | ThermoMind |
| One-liner | ThermoMind is a read-only AI diagnostic investigator for gas-turbine power generation. It combines authentic operating measurements, reproducible anomaly analysis, Meta Muse Spark reasoning with real tool use, and inspectable evidence to help plant engineers prioritize investigations. |
| Repository URL | `<FILL: public git URL>` |
| Demo video URL | `<FILL: unlisted video link, ≤ 3 min, follows docs/DEMO_SCRIPT.md>` |
| Live demo URL (optional) | `<FILL or "run locally per README">` |
| Team | `<FILL: names, roles, contact email>` |
| Meta model used | `muse-spark-1.3` via `https://api.meta.ai/v1` (OpenAI-compatible chat completions with function tools) |
| Meta usage summary | Model runs a bounded multi-turn tool loop over six server-side tools and drafts a validated investigation report; `meta_used=true` only for real API calls; offline preview is labelled "not a Meta inference" |
| Data | UCI Gas Turbine CO and NOx Emission Data Set (ID 551, DOI 10.24432/C5WC95, CC BY 4.0; Kaya, Tüfekci & Gürgen 2019) |
| Licence | MIT (repository); CC BY 4.0 (data) |
| Built during the event | Yes: everything written on 4 November 2026, from scratch; no prior code reused (docs/HACKATHON_WORK.md) |

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
- [ ] Repository URL, video URL, team fields above filled; form submitted before 9 PM ET

## Judging notes we want the reader to see first

1. Real data with honest provenance (no timestamps, no labels, CDP unit flagged).
2. Muse Spark doing work through tools, with a trace that can be replayed.
3. A validator that makes hallucinated evidence and control language impossible to ship.
4. Read-only by architecture; human review by contract.
5. A startup thesis with named incumbents, a narrow wedge, and metrics a pilot would have to measure.
