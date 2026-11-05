# Propose an action — advisory deliberation between software agents

> **Advisory deliberation between software agents — the human decides; ThermoMind executes nothing.**

An operator says something like *"for more electricity we need to increase the valve — should we, or would it do more harm?"*. ThermoMind does not act on that. It models the proposed change on real data, runs deterministic pre-checks, lets several Muse Spark agents argue for and against it in parallel, and hands a recommendation to a human. The human approves a plan, rejects it or defers. That decision is recorded and routed as a simulated in-app notification. Nothing is sent to a PLC, DCS, SCADA or historian, and no setpoint or command exists anywhere in this flow.

Code lives in `apps/api/app/features/deliberation/` (router prefix `/api/deliberation`) and the UI in `apps/web/src/features/deliberation/` (route `/propose`).

## 1. Flow

1. **Intent → modelled change** (`intents.py`). Every catalogue intent maps to one *primary* measurement delta, the operator's intent. It can also carry *implied* deltas of coupled measurements. Each implied delta is the least-squares slope (cov/var) over the training years 2011–2013, times the primary delta. Each one is labelled *statistical association, not causation, not physics*, and carries its slope and Pearson r.

   | intent | primary | implied (slope basis) | notes |
   |---|---|---|---|
   | raise_output / lower_output (X MW) | TEY ±X (MWh per hourly sample) | TIT, CDP, GTEP, TAT, AFDP, CO, NOX | Fuel flow is not measured, so it is qualitative only. TEY is never converted. |
   | open_igv_airflow | CDP +X | AFDP, TEY | IGV angle and air mass flow are not measured; CDP is the proxy. |
   | raise_firing_temperature (X °C) | TIT +X | TEY, TAT, CDP, CO, NOX | The p99 envelope is historical, not an OEM limit. |
   | run_with_higher_filter_dp | AFDP +X | none | AFDP rises *with* load in this data, so a slope would wrongly suggest more output from a dirtier filter. |
   | reduce_cooling_water | none | none | **Not observable in this data; qualitative only.** No number is produced. |
   | custom | the operator's explicit deltas | none | Free text plus deltas. |

2. **Deterministic pre-checks** (`prechecks.py`). These produce numbered *constraint findings*. Each finding has a status (`ok/info/watch/concern/exceeds/unavailable`), a provenance badge and the module that produced it. Basis: the real rows of the case window. The synthetic overlay is *not* applied.
   - **Sensitivity of the primary delta.** Uses `app.plant.sensitivity.simulate_change`, which gives the model ΔTEY and an OOD check. 0 rows outside the training range is ok; under 25 % is watch; 25 % or more is concern.
   - **Joint model check.** All model-input deltas are applied together and the baseline model is re-run. It reports whether the model reproduces the intended ΔTEY.
   - **Implied deltas vs the training range.** Weak associations (|r| < 0.3) are named.
   - **TIT vs the training-years p99 and max** (`features.grid.readiness.training_stats`). Above max is `exceeds`; above p99 is `concern`.
   - **Emissions screening.** CO and NOx are compared with the year p95 (`features.emissions.engine.p95`). The check also says whether the window already sits near that threshold. This is a screening level, not a permit limit.
   - **Electrical thermal margins at the implied load.** Uses `features.thermal.engine.evaluate` with demand multiplier (TEY+X)/TEY. The thermal feed is simulated and its ratings are assumptions.
   - **Grid-readiness headroom.** Uses `features.grid.readiness.compute_readiness`. The 160 MW nameplate is an ASSUMPTION.
   - A failing check is shown as `unavailable` with its reason. It is never hidden.
3. **Parallel agents** (`deliberate.py`). One Muse Spark agent runs per plant subsystem (`app.plant.subsystems.SUBSYSTEM_REGISTRY`). A **constraints & safety** agent runs alongside them and reviews only the findings.
   - They share a bounded thread pool and each call is capped at 3000 max_tokens.
   - Subsystem agents get one tool round: `simulate_change` and `get_sensor_window`, reused from `app.plant.whatif.PlantTools` and pre-bound to the window.
   - Each agent returns `{verdict: support|oppose|neutral|insufficient_evidence, confidence, reasons[], harms[], prerequisites[], tool_numbers_cited[]}`.
4. **Aggregator** (the "deliberation chair"). It returns `{recommendation: proceed_with_conditions|do_not_proceed|insufficient_evidence, summary, dissent[], conditions[], what_could_go_wrong[] (domino chain), rehearsal_suggestion, who_must_approve[]}`.
   - **Consensus counts are computed by software** from the verdicts, never by the model.
   - Deterministic guard rails apply:
     - An unobservable change is forced to `insufficient_evidence`.
     - An `exceeds` finding under a "proceed" recommendation is called out in `guard_notes`.
     - `shift_supervisor` and the owners of the involved subsystems are always added to `who_must_approve`. So is anyone a flagged finding implicates.
     - Unknown persona ids are dropped.
5. **Validation.** Every model-written field goes through pydantic. It is then scanned with the report validator's `UNSAFE_PATTERNS`, which include the grid and electrical patterns, and with `DATE_PATTERNS`. Recommendations must be observations, conditions or options, never commands. A failure gets **one rewrite**. After that comes a **deterministic fallback** built from the pre-checks:
   - per agent: a stand-in verdict, labelled `fallback=true`, that never says "support";
   - for the outcome: `source="deterministic_fallback"`, and the session status becomes `needs_review`.
   - With no key configured, the whole run is offline and deterministic, labelled `offline (no Meta call)`.
6. **Rehearsal (optional).** If `app.simulator` is importable and exposes `service.engine` with `rehearse/run_change/simulate/run`, the change is run for at most 120 steps. That is a software model only. Otherwise the session records `rehearsal.status="unavailable"` with the reason. The simulator is being built by another workflow and was not importable when this was written.
7. **Persistence and polling.** Sessions are saved in sqlite table `deliberations` (newest 500 kept). Each one carries per-agent events: model requests and responses with latency and tokens, tool calls, rewrites, validation and fallback.
   - `POST /api/deliberation/propose` returns `status: "running"` at once.
   - The UI polls `GET /api/deliberation/{id}`; agent cards fill in as each agent finishes.
   - At most **2** deliberations run at once (module-level `BoundedSemaphore(2)`); a further POST gets **HTTP 429**.

## 2. How the human decision is recorded

`POST /api/deliberation/{id}/decision {decision: approve_plan|reject|defer, persona, comment}`:

- The decision is appended to `decisions[]` on the stored session, with persona, comment, UTC time, `routed_to` and `executed: false`. The history is kept; the last entry is the current decision.
- It is routed to the decider's supervisor from the persona roster. A persona with no supervisor (plant manager) records to itself. The route is a **simulated in-app notification** (`plant_notifications`) that names the deliberation, the intent, the agents' recommendation and "ThermoMind executed nothing".
- On `approve_plan`, a work request titled "Approved plan (human decision): <intent>" is created **only if** `app.plant.work_requests` offers a create function that works without an investigation. Today it offers none (`create_for_investigation` needs an investigation), so only the notification is created, and `routing_note` says so.
- A decision is refused with 409 while the deliberation is running, or if it failed.
- The UI shows: *"Recorded; routed to <supervisor>; nothing was executed"*.

There is no authentication: personas are demo accounts, as everywhere else in the plant layer.

## 3. Endpoints

- `GET /api/deliberation/intents`
- `POST /api/deliberation/propose[?wait=true]`. Body: `{case_id? | year,start,end?, intent_id | custom{text,deltas}, magnitude?, persona?}`. The persona can also come from `X-Persona`.
- `GET /api/deliberation?case_id=&limit=`
- `GET /api/deliberation/{id}`
- `POST /api/deliberation/{id}/decision`

Errors: 404 for an unknown case, intent, persona or deliberation; 422 for bad input (magnitude out of range, partial window, delta beyond 3× the training std); 409 for a decision on a running deliberation; 429 when busy.

## 4. Honesty limits

- **This is not a plant model.** Implied deltas are historical co-movement in one plant's hourly aggregates. They carry no physical coupling, control logic, transients or ramp rates. The baseline is a gradient-boosted tree, flat outside its training range.
- **TEY is energy per hourly sample (MWh, as published).** "+X MW" is modelled as +X MWh per hourly sample. It is never converted.
- **Thresholds are historical or screening levels, not OEM, grid-code or permit limits.** This covers the TIT p99, the CO/NOx year p95 and the thermal alarm values, which are planning assumptions.
- **Many quantities are not in the data:** fuel flow, valve or IGV positions, cooling water, and hot-gas-path life consumption. Agents and fallbacks say so instead of inventing numbers.
- **The agents' verdicts are model opinions** over the numbers above. Consensus is a vote count, not a probability of safety.
- The UCI data has no timestamps or fault labels. Rows are `source_year` + `row_index`.
- **The software executes nothing.** The decision record is a planning artefact; any real change follows site procedures, permits and the people who own the equipment.
