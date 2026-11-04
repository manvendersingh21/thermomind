# Grid resilience: readiness, synthetic drills and contingency options

> **Read this first.** ThermoMind did not and could not prevent the 28 April 2025 Iberian blackout. ThermoMind
> is **not a grid-control system**: it has no connection to any PLC/SCADA/DCS/EMS, issues no setpoints, no
> switching, no load transfer and no dispatch change, and its only data is a public, anonymised historical dataset
> from a single gas turbine (UCI 551, 2011–2015, hourly aggregates, no timestamps, no electrical channels).
> The honest contribution of decision support to grid events is **situational awareness** (what the plant's own
> data shows, with provenance) and **prepared operator procedures** (who verifies what, who gets notified), so
> that people who *do* have authority act faster and with better information.

## Why this matters: 28 April 2025

What the official sources say (quoted; nothing below is ThermoMind's own finding):

1. **ENTSO-E Expert Panel, final report (20 March 2026):** "The blackout occurred after an uncontrolled, rapid
   rise in system voltage and loss of voltage control on a day with multiple concurrent phenomena, accelerated by
   rapid generation output reductions and disconnections, leading to voltage instability and cascading generation
   disconnections in Spain." The report also states that "the key phenomenon in the incident was the
   non-effectiveness of voltage control within the Spanish power system", and that for conventional synchronous
   plants "[t]he reactive power output was not aligned with the TSO expectations based on the requirements under
   the applicable Operational Procedure 7.4". [S3]
2. **ENTSO-E Expert Panel, factual report (3 October 2025):** "As some generation units were consuming reactive
   power with the effect of reducing the voltage, the disconnections of these units without adequate compensation
   of loss of reactive power by other resources in the system with the capability to inject/absorb reactive power
   meant that voltages in the system increased, not only in Spain but also in Portugal." and "The over-voltage
   triggered a cascade of generation losses". The same report states, for two of the trips in the
   Badajoz area, that "the reasons for these two trips are not known". [S2]
3. **Spanish Government committee report (Council of Ministers, 17 June 2025):** "the system did not have
   sufficient dynamic voltage control capability"; "the plants that were available to control voltage and those
   that had also been programmed to do so due to technical restrictions were not regulating voltage in accordance
   with the regulations"; and "The high voltages led to a chain reaction in which the disconnection of each plant
   led to the disconnection of the next". [S1]

Context, reported but not verified by us against the primary Spanish report: the committee is reported to have
stressed that the number of synchronous plants regulating voltage that day was the lowest since the start of the
year. [S5] We do not rely on this statement anywhere in the product.

Also from the factual report, relevant to how we frame *inertia*: RoCoF "remains within the absolute range of
1 Hz/s up until 12:33:20.560, when the frequency was already around 49 Hz". [S2] The event was a voltage /
reactive-power problem first; our inertia number is shown as plant capability context, not as something that
would have changed this event.

## What the feature does

### 1. Grid support readiness — `GET /api/grid/readiness`

Query: `dataset_id, year, start, end, nameplate_mw (160), h_constant_s (5), power_factor (0.85)`.
Every number carries `provenance` (`real_observation` / `model_derived` / `assumption`) and a `computation`
string with the actual values.

| Indicator | Provenance | Computation |
|---|---|---|
| Output proxy | real | mean TEY in the window, **MWh per hourly sample** (as published; never converted to MW) |
| Headroom to nameplate | assumption | nameplate (user input) − mean TEY |
| Kinetic energy | assumption | E = H × S, S = nameplate / pf (MVA). Default H = 5 s; typical range 2.5–6 s [S4] |
| Reactive capability proxy | assumption | Q at rated P = P·tan(acos pf); circle headroom √(S² − P²) at current output (ignores field-heating / under-excitation limits; OEM curve governs) |
| TIT margin | real | training-years (2011–2013) p99 of TIT − window max. **Historical envelope, not an OEM limit.** |
| AFDP level | real | window median and its percentile rank within training years; intake restriction reduces available output |
| Ambient AT | real + model-derived | window mean AT; OLS slope of TEY vs AT over training years (correlational, confounded by dispatch) and implied effect vs training-median AT |

Observed on the real dataset (2014 samples #1200–#1319, defaults): mean TEY 134.7 MWh, TIT window max 1100.0 °C vs
training p99 1100.3 °C (margin 0.3 °C → "limited"), AFDP median 3.63 mbar (percentile rank 31 %), training slope
TEY~AT −0.42 MWh/°C (r −0.19), E ≈ 941 MW·s. The TIT result illustrates the "historical envelope" caveat: TIT in
this dataset clusters near ~1100 °C at high load, which may reflect a temperature-controlled operating ceiling.

### 2. Synthetic grid-event drill — `POST /api/grid/drill`

Body: `{dataset_id, year, start, end, event: "frequency_dip"|"overvoltage"|"load_step", use_meta, seed?,
nameplate_mw?, h_constant_s?, power_factor?}` (window ≥ 48 rows).

* **S05_GRID_EVENT overlay** (implemented in `app/features/grid/drill.py`, not in the shared scenario registry):
  on a deep copy of the real window, TEY × 0.88 (−12 %) for 20 samples starting at row n/3; TIT, GTEP and CDP
  move by `slope_train × ΔTEY` where the slopes are OLS fits against TEY over the training years. Labelled
  `synthetic=true`; the original rows are never mutated (tested).
* The dataset has **no frequency, voltage or reactive-power channel**, so the event type changes only the brief's
  framing; the data overlay is the same plant-side load-step proxy in every case, and the brief says so.
* Evidence: TEY step (pre-step mean, step mean original vs overlay), co-movement per channel with the training
  slope and r, data quality (missing, overlay samples outside training range), capability numbers (assumptions).
* Brief: with `use_meta=true`, **one** Muse Spark call (`muse-spark-1.3`, `max_tokens` 3500, JSON mode) with the
  operator-support system prompt; validated with pydantic, the shared `UNSAFE_PATTERNS` and `DATE_PATTERNS` from
  `app/agent/report_validator.py`, an allowed-verb rule for `operator_verifications`
  (verify/check/confirm/monitor/communicate/escalate/prepare) and a "cite a number" rule; at most **one** rewrite;
  otherwise a deterministic offline brief labelled `[OFFLINE DETERMINISTIC]` (`mode=offline_fallback`). The
  disclaimer is fixed server-side. Drills are persisted in SQLite table `grid_drills`
  (`GET /api/grid/drills`, `GET /api/grid/drills/{drill_id}`).

### 3. Contingency options — `POST /api/grid/contingency`

Body: `{dataset_id, year, start, end, shortfall_mw | constraint: "transformer_thermal"|"line_limit"|"unit_derate",
assumptions{...}}`. Uses a **SIMULATED** local topology (`simulated: true`): GT unit → step-up transformer
(200 MVA) → line A (120 MW) → SS-A (40 MW spare) and line B (80 MW) → SS-B (25 MW spare), optional second unit
(0 MW). All capacities are assumptions. Options are enumerated for **human evaluation** — partial derate of this
unit (bounded by a minimum-stable-load assumption, with TIT margin context), shift to a second unit, request TSO
re-dispatch (external, TSO's decision), spare capacity at SS-A/SS-B (bounded by spare and line headroom) — each with
`covered_mw`, `residual_shortfall_mw`, prerequisites (grid-code/TSO approval, switching only by authorised
personnel under permit, protection settings check), who to notify, and a computation string. Ranked by residual
shortfall, then by least external dependency. Disclaimer: "Options for human evaluation. No switching, load
transfer or dispatch change is performed by this software."

## Limits (non-exhaustive)

* Hourly aggregates cannot show second-scale grid dynamics; every drill is a tabletop aid, not a simulation of
  plant or grid response.
* Nameplate, H, power factor and all network capacities are user assumptions. The reactive proxy is not a
  capability curve. TIT p99 is not an OEM limit.
* The plant is undisclosed and the data anonymised; nothing here describes any Iberian asset.

## Sources

* [S1] La Moncloa — Council of Ministers press conference, 17 June 2025 (Government committee report on the
  28 April blackout):
  https://www.lamoncloa.gob.es/lang/en/gobierno/councilministers/paginas/2025/20250617-council-press-conference.aspx
* [S2] ENTSO-E Expert Panel, *Grid Incident in Spain and Portugal on 28 April 2025 — Factual Report*, 3 October
  2025 (Ch. 1, pp. 9–12): https://www.entsoe.eu/publications/blackout/28-april-2025-iberian-blackout/ (PDF:
  https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Publications/2025/iberian-blackout/entso-e_incident_report_ES-PT_April_2025_06.pdf);
  press release: https://www.entsoe.eu/news/2025/10/03/28-april-blackout-in-spain-and-portugal-expert-panel-releases-comprehensive-factual-report/
* [S3] ENTSO-E Expert Panel, *Final Report on the Grid Incident in Spain and Portugal on 28 April 2025*,
  20 March 2026 (Ch. 1, §1.1 and §1.4.1): same ENTSO-E page as [S2].
* [S4] Fernández-Guillamón, A., Gómez-Lázaro, E., Muljadi, E., Molina-García, Á. (2019). *Power systems with high
  renewable energy sources: A review of inertia and frequency control strategies over time.* Renewable and
  Sustainable Energy Reviews 115:109369. https://doi.org/10.1016/j.rser.2019.109369 (preprint
  https://arxiv.org/abs/2004.02951), Table 1: thermal (2-pole) H 2.5–6 s (citing Kundur et al., 1994); thermal
  (gas) 90–120 MW: 5 s; combined cycle 115 MW: 4.3 s.
* [S5] Balkan Green Energy News, "Spain's voltage control was insufficient at time of April blackout" (secondary
  report of the Government committee):
  https://balkangreenenergynews.com/spains-voltage-control-was-insufficient-at-time-of-april-blackout/
* Dataset: Kaya, H., Tüfekci, P. & Gürgen, F. (2019). Gas Turbine CO and NOx Emission Data Set. UCI Machine
  Learning Repository. https://doi.org/10.24432/C5WC95 (CC BY 4.0).
