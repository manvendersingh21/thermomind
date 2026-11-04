# Collaboration layer: who decides what, one shared case record, domino map, onboarding

Read-only decision support. Nothing in this layer writes to a PLC, DCS, SCADA or historian. Nothing issues control commands. Nothing sends email, SMS or pages.

- Backend: `apps/api/app/features/collab/` (router `prefix="/collab"`, mounted under `/api` by main.py's optional-package loop).
- UI: `apps/web/src/features/collab/` (routes `/autonomy` and `/onboarding`, plus panels embedded on the case page and the Ask page).
- Tests: `apps/api/tests/test_collab.py`.

## The story

1. **Alert.** An investigation screens a data window. The agent computes the evidence and drafts a validated case report. *(agent, automatic, read-only)*
2. **Routed.** The plant router creates one work request for the technician who owns the rank-1 hypothesis, plus their supervisor. Notifications are simulated in-app only. *(agent, automatic)*
   - The autonomy policy then logs a decision for the case: `auto_triaged_no_action` or `requires_human` (see the policy below).
3. **Technician asks the plant.** The technician runs a what-if (`/ask`) and opens the **domino map** on the case. The map shows which subsystem is implicated, what lies downstream, which measurements historically move together, and who owns each part. *(the human asks; agents answer)*
4. **Supervisor approves next steps.** Every recommended next step carries `requires_supervisor_approval = true`. Work-request status changes are made by people in the inbox. *(human)*
5. **Handover drafted.** The shift handover (`/ops`) is a draft that the shift supervisor signs off. *(agent drafts; human signs off)*
6. **A new joiner reads the onboarding brief** (`/onboarding`). The brief is AI-drafted and the joiner verifies it with their supervisor. *(agent drafts; human verifies)*

**One truth for two teams.** On every case page, the **case activity feed** shows all of these steps on one timeline, so operations and maintenance read the same record.

## Policy P-01: who decides what (`GET /api/collab/policy`)

| level | meaning | examples |
|---|---|---|
| `agent_auto` | Read-only computation, routing, logging or drafting. Always logged and reversible. | Screen a window and compute evidence; draft the case report; route to persona + supervisor; recall reviewed precedents; draft handover / onboarding; auto-triage (below). |
| `human_review` | An agent drafts or proposes; a named person decides. | Accept or reject a case report; acknowledge, close or dismiss a work request; approve what-if next steps; sign off a handover; reopen an auto-triaged case. |
| `human_only` | Outside ThermoMind. **The software has no path for these.** | Maintenance and inspections in the field (under permit); electrical switching or isolation; any plant control (setpoints, load, fuel, valves, trips). |

**Auto-triage.** `apply_autonomy_policy(inv)` is called in `services.run_investigation_pipeline` right after the plant routing hook (guarded import; never raises). It records `auto_triaged_no_action` **only if every condition holds**:

1. Status is `completed` and the case has a validated report.
2. Severity is `informational`.
3. Real data only: `scenario_label == real_only`, the scenario is not synthetic, and no evidence is synthetic.
4. No evidence carries `notable_deviation`, `isolated_single_sensor` or `out_of_training_range`, and every item has `data_quality == pass`.
5. No main-signal evidence (AFDP, TEY residual, CDP, TIT, TAT, GTEP, AT, AH, AP) has |z| ≥ 2.
6. No notable CO/NOx deviation (|z| ≥ 2 on real rows, window vs reference), when it can be computed.

When the case is auto-triaged:
- The decision row is stored: `{case_id, decision, reason, policy_id: "P-01", ts_utc, reversible: true, conditions[...], routed_personas}`.
- One simulated info notification goes to `control_room_operator`: "auto-triaged by policy P-01; no human action required; reversible".
- The investigation, its report and its work request are **not changed**.

Any persona can reopen the case: `POST /api/collab/decisions/{id}/reopen` records `human_override_reopened`.

Otherwise the decision is `requires_human`, listing the failed conditions and the routed personas. Anything synthetic, or with notable evidence, is never auto-triaged.

**Backfill.** `POST /api/collab/policy/apply-existing` applies the policy to stored cases that have no decision yet. It only writes log rows.

**Counters** (`counts`) are taken over the latest decision per case.

**On today's DB.** Of the 14 stored cases, 2 are `informational`. One of them, case_b1d8db08ff82 (S01, real), would satisfy the evidence conditions. Its CDP_segments item has z = -6.9, but its flag is `coincident_with_other_sensors`, which is not a notable flag, and CDP_segments is not a main signal. The other is synthetic (S04).

## Case activity feed (`GET /api/collab/cases/{case_id}/activity`)

A read-only aggregation, ordered by timestamp. Each item is `{ts_utc, actor, actor_kind: agent|persona|human|system, kind, summary, link}`.

Sources:
- the investigation: created, agent tool calls, validator pass/reject/rewrite, report accepted/fallback, completed (mode, tool calls), human review;
- `recall_similar_cases` tool calls, shown as "precedents recalled";
- plant work requests and their status history;
- simulated notifications;
- policy decisions;
- what-if sessions on the case;
- handover notes that include the case.

Other workstreams' tables are opened `mode=ro`. A missing table becomes `sources[name] = false` and contributes no items; it never causes an error.

## Domino map (`GET /api/collab/dependency-graph?case_id=&measurement=&delta=`)

**Nodes**
- The 5 subsystems from `plant/subsystems.py`, plus the 11 measurements.
- Layers run left to right: intake → compressor → combustion/turbine → exhaust & generator.

**Edges**
- `physical`: the generic gas-turbine flow order. This is background knowledge, not plant data.
- `membership`: measurement → its subsystem.
- `statistical`: |Pearson r| ≥ 0.4 over the training years 2011–2013, taken from `plant.sensitivity.training_stats`, with the least-squares slope. Each is labelled *"statistical association, not causation"*. The real DB has 21 such edges.

**Implicated measurement.** It is chosen from the case's rank-1 hypothesis and the largest |z| among that hypothesis's measurements. For example, for case_76d34565b3dc it is AFDP, via ev_afdp_02 (|z| = 4.77).

**Domino path.** A BFS from the implicated measurement over membership and downstream physical edges (e.g. `m:AFDP → intake → compressor → combustion_turbine → exhaust_emissions, generator_output`). Its statistical neighbours are flagged separately.

**What-if change.** When a change is given, `plant.sensitivity.simulate_change` annotates the expected ΔTEY. This is MODEL-DERIVED and ceteris paribus. Live example: AFDP +1 mbar on that case gives ΔTEY mean +0.0099 MWh (min −0.323, max +0.261), not OOD.

**Node detail.** Each node carries its description, how it works, its owner persona, and read-only "what to check" wording. A test scans that wording with `UNSAFE_PATTERNS`.

## Onboarding brief (`POST /api/collab/onboarding {persona}`, `GET /api/collab/onboarding?persona=`)

**Generation**
- One Muse Spark call (`MetaClient`, max_tokens 8000, JSON mode) over a structured context: the persona, supervisor and reports, the roster, the subsystem registry, measurements, the routing and escalation rules involving the persona, and its open work-request case ids.
- If validation fails, one bounded rewrite follows, then a deterministic fallback labelled *"offline fallback — deterministic …"* or *"… Meta was called Nx but its text was rejected"*.

**Validator**
- Pydantic schema.
- Subsystem ids, measurement keys and persona ids (including persona-like tokens in free text) must exist.
- Case ids, whether in `current_open_items` or in the text, must be stored cases.
- `UNSAFE_PATTERNS` and `DATE_PATTERNS` (no dates, weekdays or clock times; "Day 1…" is used instead).

**Storage and labelling.** Briefs are persisted to the `onboarding_briefs` table. The disclaimer is always the server's wording. The UI shows the badge **"AI-drafted onboarding guide — verify with your supervisor"**.

Measured live run for `ic_engineer` (`ob_9bc9388a8938`):
- muse-spark-1.3, 1 call, accepted first pass, 44.6 s;
- 6,751 tokens, of which 4,268 were reasoning tokens.

## Endpoints

`GET /api/collab/policy` · `GET /api/collab/decisions?case_id=&limit=` · `POST /api/collab/decisions/{id}/reopen {persona?, comment?}` · `POST /api/collab/policy/apply-existing` · `GET /api/collab/cases/{case_id}/activity` · `GET /api/collab/dependency-graph?case_id=&measurement=&delta=` · `POST /api/collab/onboarding {persona}` · `GET /api/collab/onboarding?persona=`

## Honest limits

- **"Auto" means logging, triage labels, routing and drafts only.** Auto-triage does not close, dismiss or acknowledge anything, and nothing touches the plant. There is no control interface.
- **Personas are demo accounts with no authentication.** Anyone can reopen a decision as any persona.
- **The domino path is a reading aid, not a prediction.**
  - The physical order is generic background knowledge.
  - Statistical links are historical association in this plant's data, not causation.
  - ΔTEY is a single-variable sensitivity of a tree model.
- **The UCI data has limits.** It has no fault labels, no maintenance records and no timestamps, so policy conditions rest on evidence z-scores and flags, not on verified faults.
- **Onboarding briefs can be wrong.** They are drafts that the new joiner must verify with their supervisor.
