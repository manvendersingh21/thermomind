# Thermal monitoring of the electrical balance of plant

Heat detection for the **generator → generator breaker → step-up transformer → HV switchgear → busbar → grid**.
The goal is to spot overheating before it causes a failure, estimate transformer insulation ageing, and give **read-only
advisories** when thermal limits get close. That includes a what-if for data-center demand growth.

> **Simulated thermal feed derived from real load and ambient data. No thermal sensors are connected. Advisory only.
> This software does not change any load or breaker.**
>
> Every output is labelled `provenance: "simulated_from_real_load"`. This is a **planning/awareness model, not a
> measurement**. Ratings, rises, alarms and limits are **assumption inputs**. Confirm them against nameplate,
> type-test and OEM data before using any number for an engineering decision.

## Why the feed is simulated

The UCI Gas Turbine CO/NOx dataset (551) has no thermal sensors on the electrical equipment. Two of its real
columns feed the model:

| Input | UCI column | Unit (as published) | Use |
|---|---|---|---|
| Load proxy | `TEY` | MWh per hourly sample | load ratio `K = TEY / rating` (TEY is never converted to MW) |
| Ambient | `AT` | °C | transformer ambient; plus `indoor_ambient_offset_k` for enclosures |

Rows have no timestamps. The model treats consecutive `row_index` values as 1 h steps (`dt_h = 1`), but the UCI rows
are not guaranteed to be contiguous hours, so a transient across a data gap is approximate. Real rows are never
modified. The synthetic defect and the demand what-if are both applied to copies.

## Load ratio

`K = TEY / rated_mwh`. Each rating is the hourly energy at nameplate (MWh per hourly sample), so the ratio stays
dimensionless and in the published unit. Defaults are assumptions: the generator and generator breaker use
`generator_rated_mwh = 180`, which is close to the 2011–2015 max TEY of 179.5. The GSU uses `transformer_rated_mwh = 180`.
The HV switchgear and busbar use `hv_rated_mwh = 200`. Current is taken as ∝ K, which assumes constant voltage and
power factor. That assumption is not modelled further.

## Models (`apps/api/app/features/thermal/model.py`)

### 1. Step-up transformer: top-oil and hot-spot (modelled after IEEE Std C57.91, Clause 7)

```
Δθ_TO,U = Δθ_TO,R · ((K²·R + 1)/(R + 1))^n          ultimate top-oil rise
Δθ_H,U  = Δθ_H,R  · K^(2m)                           ultimate hot-spot gradient over top oil
Δθ[i]   = Δθ_U[i] + (Δθ[i−1] − Δθ_U[i]) · exp(−Δt/τ)  exact first-order step, Δt = 1 h
θ_TO    = θ_A + Δθ_TO ;   θ_H = θ_TO + Δθ_H ;   θ_A = AT
```
The initial condition is the steady state at the first sample. At K = 1 the steady-state hot spot is
`θ_A + Δθ_TO,R + Δθ_H,R` (θ_A + 80 K at the defaults). A unit test checks this.

| Parameter | Default | Note |
|---|---|---|
| `top_oil_rise_rated_k` Δθ_TO,R | 55 K | C57.91 typical (65 °C-rise transformer) |
| `hot_spot_gradient_rated_k` Δθ_H,R | 25 K | typical |
| `loss_ratio_r` R | 5.0 | load loss / no-load loss at rated |
| `exponent_n`, `exponent_m` | 0.8, 0.8 | ONAN/ONAF typical |
| `tau_top_oil_h` τ_TO | 3.0 h | |
| `tau_hot_spot_h` τ_H | 0.1 h | effectively quasi-steady at hourly resolution |
| `transformer_hot_spot_alarm_c` | 110 °C | C57.91 reference hot spot for normal life expectancy |
| `transformer_hot_spot_limit_c` | 120 °C | conservative site assumption; C57.91 allows 130 °C for planned loading beyond nameplate |
| `transformer_top_oil_limit_c` | 105 °C | shown as context only |

### 2. Transformer insulation ageing (IEEE C57.91 Clause 5)

```
F_AA  = exp(15000/383 − 15000/(θ_H + 273))       (= 1.0 at θ_H = 110 °C)
LOL_h = Σ F_AA · Δt ;  F_EQA = mean(F_AA) ;  LOL % = 100 · LOL_h / normal_insulation_life_h
```
`normal_insulation_life_h = 180 000 h` (C57.91 basis). The per-year figure `100 · F_EQA · 8760 / life` is labelled
**EXTRAPOLATED**. It assumes the window represents the whole year and is not a forecast. Only the transformer has a
standard ageing model here. The other assets get margins only.

### 3. Conductors, busbar, switchgear contacts, generator stator (I²R, quasi-steady)

```
θ = θ_amb + Δθ_rated · K²         θ_amb = AT + indoor_ambient_offset_k (default 5 K)
```
| Asset | Rated rise | Alarm / limit | Basis ("typical type-test limits, confirm with equipment data") |
|---|---|---|---|
| Generator breaker (GCB) contacts | `contact_rated_rise_k` 65 K | 95 / 105 °C | IEC 62271-1 / IEEE C37.20.2 silver-plated contacts: 65 K rise over 40 °C → 105 °C |
| HV switchgear (HVSG) contacts | 65 K | 95 / 105 °C | same |
| HV busbar (BUS) | `busbar_rated_rise_k` 30 K | 80 / 90 °C | IEC 62271-1 bare-copper bolted joints: 50 K rise → 90 °C limit; 30 K design rise assumed |
| Generator stator (GEN) proxy | `generator_rated_rise_k` 80 K | 130 / 155 °C | IEC 60034-1 class B rise used on class F (155 °C) insulation |

### 4. SYNTHETIC defect `T01_HOT_CONNECTION` (off by default, `synthetic=true`)

This is a single degrading connection at the **HV switchgear** (cable termination / bolted joint):
`θ = θ_amb + c(t)·Δθ_rated·K² + ε`, where `c(t) = 1 + g·t/(N−1)` (`hot_connection_growth` g = 1.0, so 1× → 2× over
the window) and `ε ~ N(0, 0.3²)` from `numpy.random.default_rng(scenario_seed)` (seed 42 by default). Output is
deterministic per seed. The UI pulses the asset yellow and shows a SYNTHETIC badge.

### 5. Demand what-if ("what would happen if data-center demand raised our dispatch by X %")

`TEY' = TEY · m(t)`, then the whole model runs again.
- `flat`: `m = demand_multiplier` (0.5–2.0, e.g. 1.15 = +15 %).
- `diurnal_datacenter`: `m = 1 + x·(1 + 0.25·cos(2π(h − 15)/24))`, where `x = multiplier − 1` and
  `h = row_index mod 24`. h is a **notional hour, not a clock time**, because the UCI rows have no timestamps. The mean
  over a notional day equals the multiplier.

Outputs per asset are the baseline and what-if peak and the samples at or above alarm and limit. The run-level
outputs are the samples above nameplate (K > 1) and the transformer loss of life for baseline and what-if.
What-if outputs carry `what_if=true`. Caveat: the gas turbine's own capability limit (output falls with ambient),
cooling-stage changes and grid constraints are not modelled.

## Engine (`engine.py`) screening

- **State** at the last sample: `normal` < alarm − `approach_margin_k` (10 K) ≤ `approaching` < alarm ≤ `alarm` < limit ≤ `limit`.
- **Flags**: `approaching_alarm`, `above_alarm`, `above_limit`, `exceeded_alarm_in_window`.
- **Trend**: least-squares slope over the last 24 samples (`app.analytics.anomaly.trend_slope`).
- **Load-corrected rise index** for the connection group (GCB, HVSG, BUS) = `(θ − θ_amb)/(Δθ_rated·K²)`. This is the
  same `(I_rated/I)²` correction used for IR survey results. It is 1.0 for a healthy element and is not computed when K < 0.2.
  - `rising_faster_than_peers`: the index slope over the last 24 samples exceeds the peer median by > 0.002/sample.
  - `hot_connection_pattern`: the index rose ≥ 15 % (mean of the first 24 vs the last 24 samples) while every
    sibling stayed within ±5 %.
- Without the synthetic defect, the simulated feed has no defect by construction. Flags on a real-only window
  can only come from load and ambient pushing temperatures towards the alarm and limit assumptions.

## Advisories (read-only wording)

Advisories only list options for people to **EVALUATE**, and each one ends with "no action is taken by this
software." Example:

> Advisory: Step-up transformer hot-spot margin < 10 K (… K to the 110 °C alarm) at current load ratio K = …; options for the
> operator/dispatch to EVALUATE per site procedure: schedule inspection (IR survey) of Step-up transformer, review load
> allocation, consider derate planning — no action is taken by this software.

A test scans every advisory and flag message with `app.agent.report_validator.UNSAFE_PATTERNS`. No work requests are
created, because `app.plant.work_requests` only offers `create_for_investigation(inv)`, which needs an investigation.

## API

- `GET /api/thermal/assets` returns the assets in one-line order with their model and standard reference, the
  default assumptions, scenarios, demand profiles and the banner.
- `POST /api/thermal/evaluate` takes `{dataset_id="ds_uci_551", year=2014, start=1200, end=1320, assumptions{…}, scenario:"none"|"T01_HOT_CONNECTION", scenario_seed=42, demand_multiplier?, demand_profile:"flat"|"diurnal_datacenter"}`.
  It returns `status[]`, `flags[]`, `advisories[]`, `ageing`, `limits[]`, `series[]` (≤ 1000 points, bucket maxima),
  `demand`, `assumptions` (echo), `provenance`, `synthetic` and `banner`.
  It returns 422 when the window is invalid or out of range (24–9000 samples), the scenario or profile is unknown,
  an assumption is out of bounds or an alarm is at or above its limit, or the request has an unknown field.
  It returns 404 for an unknown dataset.

## Limitations

- These are planning models with assumed parameters, not measured temperatures. Real IR surveys, online monitors
  (transformer hot-spot fibre optics, DGA, switchgear wireless sensors) and OEM ratings take precedence.
- Hourly aggregates hide sub-hour peaks. Treating rows as contiguous hours is an approximation.
- Solar load on outdoor equipment, wind cooling, the cooling stages (ONAN/ONAF switching), harmonics and
  power-factor changes are not modelled.
