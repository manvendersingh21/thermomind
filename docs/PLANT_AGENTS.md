# Plant agents: personas, routing, "Ask the plant", precedent memory

This is read-only decision support. Nothing in this layer sends email, SMS or pages. Nothing writes to a PLC, DCS, SCADA or historian. Nothing issues control commands. All code is in `apps/api/app/plant/` (router: `apps/api/app/api/plant.py`). The UI is in `apps/web/src/plant/`.

## 1. Demo personas (fake accounts, no authentication)

A persona is selected by the `X-Persona` header or by `?persona=`. The UI stores the choice in localStorage under `thermomind.persona`. The default persona is `reliability_engineer`. The roster models a combined-cycle plant:

| id | role | owns / watches | supervisor |
|---|---|---|---|
| plant_manager | Plant manager | escalation for `urgent_review` | – |
| shift_supervisor | Shift supervisor (operations manager on shift) | all on-shift work | plant_manager |
| control_room_operator | Control-room operator | sees every alert; read-only acknowledgement | shift_supervisor |
| performance_engineer | Performance engineer | AT, AP, AH, TEY (operating condition) | reliability_engineer |
| reliability_engineer | Reliability engineer (condition monitoring) | owns investigations; default | plant_manager |
| mechanical_maintenance_engineer | Mechanical maintenance engineer | AFDP, CDP, TIT, TAT (intake, compressor, hot gas path) | shift_supervisor |
| ic_engineer | I&C engineer | sensor validity: CDP, AFDP, TIT | shift_supervisor |
| electrical_engineer | Electrical engineer | generator / switchyard (TEY side) | shift_supervisor |
| environmental_engineer | Environmental engineer | CO, NOX, GTEP | plant_manager |
| hse_officer | HSE officer | permits, isolation per procedure | plant_manager |
| oem_field_service | OEM field service (**external**, simulated) | TIT, TAT, hot gas path | reliability_engineer |

## 2. Routing: investigation → work request → simulated in-app notifications

`services.run_investigation_pipeline` calls `app.plant.work_requests.on_investigation_completed(inv)` right after it saves the investigation. The hook never raises. It runs for cases with status `completed` or `needs_review`, creates one `WorkRequest` per case, and sends in-app notifications. Routing uses the rank-1 hypothesis of the report. If there is no validated report, it uses the top hypothesis from the deterministic summary.

| rank-1 hypothesis | assignee | supervisor | cc |
|---|---|---|---|
| intake_restriction | mechanical_maintenance_engineer | shift_supervisor | reliability_engineer, hse_officer (field inspection) |
| sensor_issue | ic_engineer | shift_supervisor | reliability_engineer |
| operating_condition | performance_engineer | reliability_engineer | – |
| unknown / unmapped | reliability_engineer | shift_supervisor | – |

Escalations:
- Severity `urgent_review` also notifies plant_manager.
- A notable CO/NOx deviation also notifies environmental_engineer. "Notable" means |z| ≥ 2, computed at routing time on real rows as window mean minus reference mean, divided by the reference std. The evidence engine has no CO/NOx items, so this computation is separate.
- Notable `ev_tit_01` / `ev_tat_01` (|z| ≥ 2) also notifies oem_field_service (external, simulated).
- control_room_operator gets an info notification for every work request.

Each work request records:
- `assignment_label`, e.g. "Assigned to … · Supervisor … · simulated notification"
- `routed_by: "rule:<key>"`
- `notified_personas` with a reason for each
- `checks`, taken from the report's `engineer_review_checks`

Status transitions: `open → acknowledged | done | dismissed` and `acknowledged → done | dismissed`. `done` and `dismissed` are final. Any other transition returns 409, and every change is appended to `history`.

The label is shown everywhere: **"Simulated in-app notification — no email/SMS/paging integration."**

## 3. "Ask the plant" what-if console (multi-agent, Muse Spark)

A technician working in one area asks something like "what if AFDP rises by 1 mbar during my work?" The request is `POST /api/plant/whatif {case_id?, question, measurement, delta, persona?}`.

1. **Deterministic tool `simulate_change`** (`plant/sensitivity.py`). It runs on the real rows of the case window, or on the default 2014 rows [1200,1320). The synthetic overlay is not applied.
   - **Model effect:** shifts one measurement by `delta` and re-runs the production `BaselineModel`. It reports ΔTEY (mean, min, max) in MWh. This is MODEL-DERIVED and ceteris paribus. The model is a tree model, so its response is flat outside the training range.
   - **`train_range_check`:** sets the OOD flag when perturbed values leave `feature_ranges_train`.
   - **Co-movement:** Pearson r and least-squares slope of every other measurement against the perturbed one, over 2011–2013. Labelled *"statistical association in this plant's historical data, not causation, not physics"*.
   - **Input limit:** |delta| ≤ 3 × training std. Larger values return 422.
2. **One agent per subsystem, all in parallel.** The subsystems come from `plant/subsystems.py`. Each agent is a Muse Spark chat with three tools: `simulate_change` (pre-bound to the window), `get_sensor_window` (the existing `ToolRunner`, which reproduces the case's labelled overlay) and `lookup_reference`.
   - Each agent gets one tool round, then a JSON-only answer. The answer is a `SubsystemAssessment` with `owner_label` (e.g. "owner: I&C engineer") taken from the registry.
   - Limits: max_tokens 3000 per call, 5000 on the single rewrite, and a 55 s agent budget.
3. **One aggregator call** writes two of the three blocks shown to the technician. The full block order is:
   1. **How this part works.** Filled deterministically from the registry; the source is cited.
   2. **What your test could affect elsewhere.** Each effect has direction, magnitude hint, confidence, tool numbers and basis.
   3. **Recommended fix / next steps.** Maintenance and diagnostic actions only (inspect, verify, calibrate, schedule, isolate per procedure, collect data). `requires_supervisor_approval` is forced to `true`.

   The aggregator also writes `cross_impacts` and `what_to_check_before_acting`. Its max_tokens is 5000, because reasoning tokens count against it.
4. **Validation.** Answers are checked with Pydantic (`plant/schemas.py`). All text is then scanned with the investigation validator's `UNSAFE_PATTERNS` and `DATE_PATTERNS`, and a failure gets one bounded rewrite.
   - If an agent still fails, a deterministic stand-in replaces its card and is labelled as one.
   - If the aggregator fails, the session status becomes `needs_review` and the errors are listed in `validation_errors`.
5. **Persistence.** Sessions are saved in sqlite table `whatif_sessions`, with a per-agent event timeline (tool calls, latency, tokens).
   - `POST` returns `status: "running"` immediately. The UI polls `GET /api/plant/whatif/{id}`, which shows the live per-agent events.
   - `?wait=true` blocks until the run finishes.
6. **Offline.** With no key configured, the result is deterministic sensitivity only. It is labelled `mode: "offline"` and `mode_label: "offline (no Meta call)"`.

Measured live run (case_76d34565b3dc, AFDP +1.0 mbar, muse-spark-1.3): 5 subsystem agents and the aggregator all validated, in 68.7 s wall time (session `wi_7d9eda1b9821`).

### n+1: adding an agent / role
- **New plant area agent:** append one dict to `SUBSYSTEM_REGISTRY` in `plant/subsystems.py` (key, name, measurements, description, how_it_works, owner_persona). The orchestrator starts one more parallel agent, and the UI renders one more card.
- **New role:** add one `Persona` to `PERSONAS`, plus a routing or escalation rule in `ROUTING_TABLE` if it should receive work.
- **New investigation tool for the main agent:** append `{"spec", "handler"}` to `EXTRA_TOOLS` in `plant/agent_hooks.py`.

## 4. Memory = reviewed precedents (not learning, not ground truth)

`plant/memory.py` builds an evidence signature for each case. It is the z-score vector for `ev_afdp_01, ev_afdp_02, ev_tey_residual_01, ev_tey_residual_02, ev_cdp_01, ev_tit_01, ev_tat_01, ev_gtep_01, ev_at_01, ev_ah_01, ev_ap_01`, with missing values set to 0 and values clipped to ±10.

`recall_similar(case_id | evidence, k=3)` ranks stored investigations by cosine similarity. Only cases with a human review decision are included: accepted, rejected or more_data_requested. Each result returns:
- case id
- scenario
- rank-1 hypothesis
- decision, reviewer and comment
- similarity

How it is exposed:
- **To the investigation agent:** the tool `recall_similar_cases`, registered through the optional `app.plant.agent_hooks.EXTRA_TOOLS` hook in `agent/orchestrator.py`. Its system-prompt note says precedents are reviewed human decisions on similar evidence patterns, not ground truth. Their evidence ids must never be cited.
- **To the UI:** `GET /api/plant/precedents?case_id=…`.

"The system keeps it in mind" therefore means that past human review decisions are retrieved and shown as context. No model is retrained, and nothing is learned automatically.

## Endpoints
`GET /api/plant/personas` · `GET /api/plant/subsystems` · `GET /api/plant/measurements` · `GET /api/plant/inbox?persona=` · `POST /api/plant/notifications/{id}/read` · `GET /api/plant/work-requests?persona=&status=&case_id=` · `POST /api/plant/work-requests/{id}/status {status, comment}` · `GET /api/plant/sensitivity?measurement=&delta=&case_id=` · `POST /api/plant/whatif[?wait=true]` · `GET /api/plant/whatif` · `GET /api/plant/whatif/{id}` · `GET /api/plant/precedents?case_id=&k=`

## Honest limits
- The personas are fake demo accounts with no authentication. Notifications are in-app only. The OEM persona is a simulated external party.
- The UCI data has no fault labels, no maintenance records and no timestamps. The what-if numbers are a statistical-baseline sensitivity plus historical association, not a physics or thermodynamic simulation. Single-variable perturbations ignore physical coupling.
- Routing is a fixed rule table over the rank-1 hypothesis, not learned.
- Live what-if takes about 60–100 s and depends on the Meta API.
