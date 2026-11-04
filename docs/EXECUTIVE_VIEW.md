# Executive view (`/executive`)

A CEO-level page that aggregates only what ThermoMind already measures. Each KPI carries `{value, unit, provenance, source_endpoint, caveat}`. Provenance values: `real` (public UCI measurements), `model_derived` (baseline-model residuals), `simulated` (thermal model), `assumption` (depends on default assumptions), `prototype_metric` (this prototype's own store). No financial outcome, saving, availability or revenue figure is computed or claimed.

Code: `apps/api/app/features/executive/` (`overview.py`, `brief.py`, `router.py`, `schemas.py`), UI `apps/web/src/features/executive/`, tests `apps/api/tests/test_executive.py`.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/api/executive/overview?year=2014` | KPIs + rule-based "needs attention" list + open cases |
| POST | `/api/executive/brief` `{year}` | One Muse Spark call (max_tokens 8000), validated, one rewrite, else labelled fallback; stored in `executive_briefs` |
| GET | `/api/executive/briefs`, `/api/executive/briefs/{id}` | Stored briefs, newest first |

## KPIs: what each one is, and what it is not

| Group | KPI (`key`) | Provenance | What it is | What it is not |
|---|---|---|---|---|
| Performance | `tey_residual_year_mean` | model_derived | Year-mean of observed − expected TEY from the baseline model (trained 2011–2013) | Not a heat rate: the data has no fuel flow. A year offset also reflects model drift (2014 validation residual median is positive) |
| Performance | `compressor_wash_status` | assumption | Planner wash break-even status computed with the planner's default economics | Not a maintenance instruction; change the assumptions on `/planner` |
| Performance | `lost_output_rate_now` | model_derived | Rolling-median residual at the last sample vs the year's p95 rolling level (planner) | Not attributed to fouling; dispatch, ambient and drift are other causes |
| Reliability | `notable_deviation_share` | model_derived | Share of rolling 24-sample windows where the residual mean deviates from the preceding 168 samples by \|z\| ≥ 2 (evidence-engine rule, validation residual std). Computed in vectorised form from the residual series, not by running the full evidence engine per window | **Not availability.** The dataset records no outages, trips or availability; this is an availability *proxy* |
| Reliability | `instrument_health` | real | Count of sensors `ok / watch / check` from the instrument scorecard over the year | Not a diagnosis; `check` means verify the transmitter first |
| Reliability | `thermal_min_margin` | simulated | Smallest margin to alarm (K) across balance-of-plant electrical assets, thermal model on the last 120 samples of the year | Not a measured temperature; ratings are assumptions |
| Compliance | `emissions_hours_above`, `emissions_excursions` | real | Hours above the screening threshold (CO or NOX) and contiguous excursions | The default threshold is the year's own p95, so about 5 % of hours sit above it by construction; not a permit limit |
| Grid | `grid_headroom` | assumption | Assumed nameplate (160 MW) − year-mean TEY (MWh per hourly sample as output proxy) | Not grid-services revenue; nameplate is an assumption |
| Decisions | `cases_awaiting_review` | prototype_metric | Stored cases without a human review (or more data requested) | Includes demo and synthetic-overlay cases; not plant events |
| Decisions | `work_requests_open` | prototype_metric | Open / acknowledged work requests | Notifications are simulated; no CMMS is touched |
| Decisions | `deliberations_awaiting` | prototype_metric | Deliberation sessions finished without a human decision (guarded import) | Unavailable when the deliberation package is absent |
| Decisions | `human_required` | prototype_metric | Cases whose latest autonomy-policy decision is `requires_human`, plus watchdog items when exposed (guarded, read-only SQL) | Unavailable when neither package is present |
| Decisions | `investigation_wall_time` | prototype_metric | Median seconds from first model request to accepted report, live Meta cases | Not engineer time |
| Decisions | `first_pass_acceptance` | prototype_metric | Share of live reports accepted by the validator without a rewrite | Form and provenance, not diagnostic accuracy |
| People & knowledge | `precedents`, `handover_notes`, `onboarding_briefs` | prototype_metric | Reviewed cases; handover drafts; onboarding drafts (tables read-only, counted if present) | Drafts, not signed documents |
| Safety & OT security | `control_write_path` | prototype_metric | Control-system connector capabilities (`read=False, write=False`) | Not an OT-security audit; other connectors are simulated |
| Safety & OT security | `cited_ids_resolving` | prototype_metric | Share of evidence IDs cited in stored reports that exist in their case | Not correctness of the reasoning |

## Attention rules (deterministic)

| Rule | Persona | Link |
|---|---|---|
| thermal margin to alarm < 10 K (the thermal engine's default approach band) | electrical engineer | `/thermal` |
| planner wash status = "consider scheduling a wash" | performance engineer | `/planner` |
| any instrument with status `check` | I&C engineer | `/instruments` |
| watchdog / triage `human_required` > 0 | reliability engineer | `/watchdog` |
| deliberations awaiting decision > 0 | plant manager | `/propose` |
| open work requests > 0 (info) | shift supervisor | `/inbox` |
| cases awaiting review > 0 (info) | reliability engineer | `/investigations` |
| emissions screening excursions > 0 (info) | environmental engineer | `/emissions` |

## Executive brief validator

The model sees a compact JSON of the overview. The draft is rejected (one rewrite, then deterministic fallback labelled `OFFLINE FALLBACK` or "Meta was called but its text was rejected") when: it is not the JSON schema; it matches any `UNSAFE_PATTERNS` (control language) or `DATE_PATTERNS`; it contains currency amounts or savings claims; it cites a case id not in the payload; it names an unknown owner persona; or **any number in its text is not in the payload** (regex over numbers after stripping identifiers like `case_…`, `S02_…`, `p95`; tolerance = rounding to the written precision or 0.5 % relative; `30` is allowed as the "next 30 days" label). Disclaimer: "AI-drafted executive brief from prototype metrics on public data; not financial advice; no savings claimed".

## What this page is not

Not a financial dashboard, not an availability report, not a compliance report, not a control interface. It is a read-only summary of prototype metrics on one public plant's data (2011–2015, no timestamps) plus simulated subsystems.
