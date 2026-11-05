# Plant simulator (`/simulator`)

A software-only 0-D (lumped) model of a single-shaft heavy-duty gas turbine, replayed against real UCI ambient rows. Everything it outputs is labelled `SIMULATED_PLANT`. Code: `apps/api/app/simulator/{physics,engine,calibration,router}.py`; UI: `apps/web/src/features/simulator/SimulatorPage.tsx`.

## What is modelled (as implemented in `physics.py`)
- Working fluid: `cp(T) = 1005 + 0.1(T-300)` J/(kg K) for air and gas alike (documented simplification); enthalpy and entropy function are its integrals; isentropic temperature by Newton solve of `s(Ts) - s(Tin) = R ln(p_out/p_in)`, `R = 287`.
- Intake filter: `dP_f = k_f (m/m_ref)^2 (1 + fouling)` gives AFDP; `p1 = p_amb - dP_f`, `T1 = AT + 273.15`.
- Compressor: corrected speed `Nc = w sqrt(288.15/T1)`, corrected flow `mc = phi(lam) Nc m_ref (1 - 0.5 comp_foul)`, `PR = 1 + (PR_ref - 1)(mc/m_ref) Nc`, `eta_c = eta_c_ref (1 - comp_foul)`; CDP is reported as `p2/1e5` (numerically bar; the UCI "mbar" label is as published and unit is under validation).
- Combustor: energy balance with LHV 47 MJ/kg, `eta_b = 0.995`, 4 % pressure loss; `T3 = TIT_lo + (TIT_hi - TIT_lo) lam` (the load command sets turbine inlet temperature); fuel flow follows from the balance.
- Turbine/exhaust: `dP_ex = k_ex (m_gas/m_ref)^2` gives GTEP; `h4 = h3 - eta_t (h3 - h4s)`; TAT = `T4 - 273.15`.
- Shaft: `P_mech = W_t - W_c - P_loss`, `P_elec = eta_g P_mech`; TEY = electrical MW, read as MWh per hourly-equivalent sample.
- Emissions (empirical): NOx = `a exp(b (T3 + 150 - 1600)) exp(-19 (w - 0.00634))`; CO = `c (1 + d (1 - load_fraction)^2)`.
- Dynamics (`engine.py`): states `[w, z, lam]`, dt = 1 s, classical RK4. Swing equation with H = 5 s on `P_rated`, load-frequency damping D = 2, governor droop R = 0.05 plus PI term (Ki = 0.5, anti-windup), actuator lag 2 s. A per-step energy-closure percentage is recorded.

## What is assumption
Fixed constants (LHV, `eta_b`, 4 % combustor loss, flame-temperature offset 150 K, H, droop, Ki, D, actuator lag), the shared air/gas `cp(T)`, the linear `lam -> TIT` and `lam -> IGV flow` maps, and the NOx/CO functional forms are modelling choices, not measurements. The fitted parameters are listed in `DEFAULT_PARAMS` (starting values) and refit at runtime.

## Inputs, outputs, faults
- Real replayed inputs: AT, AP, AH rows from `data/raw/uci_551/gt_<year>.csv` (year 2011-2015, `start_index`, `rows_per_hour` simulated seconds per row, no timestamps invented). Dispatch setpoint = the real TEY of the replayed row, clipped to model capacity (`dispatch_clipped` flag).
- Simulated outputs: AFDP, GTEP, TIT, TAT, TEY, CDP, CO, NOX. Per-channel provenance in each record is `real_input`, `simulated` or `synthetic_fault`.
- Synthetic faults (`synthetic=true`): physics faults `intake_fouling` (rate per simulated hour, 0-50), `compressor_fouling` (efficiency loss 0-0.2), `hot_day` (+dAT, 0-25 C); sensor faults `sensor_bias`, `sensor_drift` (per simulated hour), `sensor_spike` (2 % of steps), `sensor_stuck`, each on a chosen channel.

## Calibration
Method (`calibration.py`): sample 200 rows (seed 551) from 2011-2013; per row solve the load command so model TEY equals real TEY; `scipy.optimize.least_squares` fits the physics parameters on std-normalised TIT, TAT, CDP, AFDP, GTEP; then NOx (a, b) and CO (c, d); score MAE on every 2014 row (held out). Parameters that ended at their bounds are reported in `params_at_bounds`.

Real output of one run of `get_calibration()` on this machine (2014, 7,158 rows; units as published; mean in brackets). Runtime values from `GET /api/simulator/calibration` are authoritative:

| Channel | MAE | 2014 mean |
|---|---|---|
| TIT | 6.08 | 1078.8 |
| TAT | 3.47 | 547.6 |
| CDP | 0.0997 | 12.02 |
| AFDP | 0.392 | 3.91 |
| GTEP | 0.749 | 25.74 |
| NOX | 9.70 | 60.07 |
| CO | 0.787 | 2.08 |
| TEY | 0.0027 | 132.9 |

TEY MAE only reflects the load-solve interpolation, since TEY is the dispatch input. Parameters at bounds in that run: `eta_c`, `P_loss`. 0.24 % of 2014 rows needed a load command outside [0, 1]. These are fit errors of a simplified model, not a validation of any plant.

## API (mounted under `/api/simulator`)
`POST /run` (start, pause, resume, stop, reset, speed), `GET /state`, `GET /history?n=`, `GET /stream` (SSE, at most 4 Hz), `POST /faults`, `DELETE /faults/{id}`, `POST /register-window` (registers the last N simulated records, one year only, as a dataset so an investigation can run on it; `source=SIMULATED_PLANT`, warnings attached, no timestamps), `GET /calibration`.

## Limits
0-D model calibrated to one plant's public data; not a digital twin of any specific facility; simulator controls act on the model only. The governor in the model is the simulated plant's own control; nothing is written to any PLC, DCS or historian. No real fault labels exist, and injected faults are synthetic.
