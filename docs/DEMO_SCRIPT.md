# Demo script (3 minutes)

This is the storyboard of the submitted video. It is recorded automatically from the running product by
`scripts/record_demo.py` (real clicks in headless Chromium, captions + edge-tts voice-over); see
[`docs/VIDEO.md`](VIDEO.md) for the exact command, the measured duration and the upload checklist. A presenter
doing it live follows the same path and can read the "Say" column.

Preconditions: `make data`, `make train`, `make seed` done; `.env` has `MODEL_API_KEY`; the API serves the
built UI on http://localhost:8000; the live Muse Spark case for `S02_INTAKE_RESTRICTION`
(`case_76d34565b3dc`) exists. The video never starts a new live run (it takes 1–2 min); it opens the stored
`meta_live` case. Segments whose route is not served at record time are skipped with their narration.

| Time (≈) | Route | What is on screen | Say (= caption) |
|---|---|---|---|
| 0:00–0:15 | `/` | REAL UCI TURBINE DATA badge, plant schematic with real tag values | "ThermoMind reads a gas turbine's real public data and investigates deviations with evidence, never touching controls." |
| 0:15–0:35 | `/investigations/case_76d34565b3dc` | META LIVE · muse-spark-1.3 badge → ranked hypotheses → click `ev_afdp_01` → evidence drawer (computation) → agent timeline, "show args" | "In this live case, Meta's Muse Spark 1.3 ranks hypotheses, and every evidence ID opens the deterministic computation behind it." · "Muse Spark calls the deterministic tools itself. Every call, result, latency and token count is stored, so every number is traceable." |
| 0:35–0:55 | same case → `/twin/case_76d34565b3dc` (if served) | "Where to look" panel: highlighted generic schematic; 3D twin hot-spot when the route exists | "Where to look maps the top hypothesis onto a generic plant schematic. This scenario is a synthetic overlay on real rows, and it is labelled synthetic at every layer." · "A 3D twin marks the same spot, on a generic plant model." |
| 0:55–1:15 | `/inbox` | Routed work request: assignee + supervisor, simulated in-app notification badge, "SIMULATED WORKFLOW · NOT A CMMS" | "Findings route to the responsible engineer and their supervisor. The notifications are simulated, and nothing is sent to a maintenance system." |
| 1:15–1:45 | `/propose` (if served) | Pick the S02 case, intent "raise output by 5 MW", agent verdict cards, consensus, dissent, recommendation, human decision, "nothing executed" | "Before anyone acts on a proposal, like raising output by 5 megawatts, the subsystem agents confer on what it would do elsewhere in the plant." · "Verdicts, consensus and dissent lead to a recommendation. The human decides — and nothing is executed." |
| 2:10–2:30 | `/ops` → `/autonomy` (if served) | Muse Spark shift-handover draft (DRAFT — requires shift supervisor sign-off); who-decides-what policy | "Routine triage and drafts run without a human, like this Muse Spark shift handover. Anything that touches the plant always needs one." · "The autonomy policy spells out who decides what." |
| 2:30–2:50 | `/evaluation` | Holdout (2015, untouched) vs naive baselines, production baseline vs GPU challenger table, safety disclaimer | "On the untouched 2015 holdout, the baseline's mean error is 1.29 megawatt-hours, versus 4.13 for a naive previous-value baseline. The GPU challenger is a benchmark only, and this is not a validated safety system." (numbers are read from `GET /api/models/evaluation` at record time; see `docs/EVALUATION.md`) |
| 2:50–3:00 | `/` | Overview, repo URL github.com/manvendersingh21/thermomind | "Built today, from real public data, with humans in the loop." |

## Fallbacks

- Meta API slow or down: everything above uses stored cases; nothing in the video waits on Meta. To show a live run,
  record the separate proof video with `python scripts/record_demo.py --live-only` (unedited 1–2 min wait).
- A route from the table is missing in the build: the recorder skips that segment and its narration and prints
  `route … NOT served -> segment skipped`; the video gets shorter, never broken.
- Network blocked for the TTS service: `python scripts/record_demo.py --no-narration` (captions only).

## Things not to say

No "detects faults", no "prevents outages", no accuracy percentage, no savings claims, no customer names, no
"trained on plant X". Say "evidence", "hypothesis", "draft", "review". The UCI data has no timestamps and no fault
labels; S02/S03 patterns are synthetic overlays on copies of real rows.
