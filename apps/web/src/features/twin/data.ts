/**
 * Data binding for the 3D twin. Every value comes from an existing read-only API:
 *  - /api/investigations/{id}            (case window, hypotheses, evidence)
 *  - /api/datasets/ds_uci_551/series     (REAL measurements; TEY with MODEL-DERIVED expected)
 *  - /api/scenarios/preview              (SYNTHETIC overlay values for synthetic cases)
 *  - /api/thermal/evaluate               (SIMULATED electrical temperatures)
 *  - /api/emissions/window               (screening thresholds + excursions)
 *  - /api/plant/personas, work-requests  (routing / responsible persona)
 *  - /api/connectors/historian/latest    (optional SIMULATED historian replay)
 */
import { useEffect, useMemo, useState } from "react";
import { errorMessage, getInvestigation, getSeries, previewScenario } from "../../api/client";
import type { Investigation, SeriesResponse } from "../../api/types";
import { getHistorianLatest } from "../connectors/api";
import type { HistorianLatest } from "../connectors/types";
import { getEmissionsWindow } from "../emissions/api";
import type { EmissionsResponse } from "../emissions/types";
import { evaluateThermal } from "../thermal/api";
import type { AssetId, ThermalEvaluateResponse } from "../thermal/types";
import { getPersonas, listWorkRequests } from "../../plant/api";
import type { PersonasResponse, WorkRequest } from "../../plant/types";
import type { LiveState } from "./types";

export const DATASET_ID = "ds_uci_551";
export const TWIN_MEASURES = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"] as const;
export const DEFAULT_WINDOW: TwinWindow = { year: 2014, start: 1200, end: 1320 };
export const MAX_WINDOW = 2000;

export interface TwinWindow {
  year: number;
  start: number;
  end: number; // exclusive
}

export interface TwinSeries {
  rows: number[];
  /** measure → values aligned with rows */
  values: Record<string, (number | null)[]>;
  expectedTey: (number | null)[];
  units: Record<string, string>;
  downsample: number;
  /** measures whose values are SYNTHETIC overlay (synthetic cases only) */
  syntheticMeasures: string[];
}

export interface TwinData {
  loading: boolean;
  errors: string[];
  investigation: Investigation | null;
  window: TwinWindow;
  series: TwinSeries | null;
  thermal: ThermalEvaluateResponse | null;
  emissions: EmissionsResponse | null;
  personas: PersonasResponse | null;
  workRequests: WorkRequest[];
}

const clamp01 = (x: number) => (Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : 0);

/** Visual normalisation ranges (approximate UCI value ranges; visuals only). */
export const NORM: Record<string, [number, number]> = {
  TEY: [100, 180],
  TIT: [1000, 1101],
  AFDP: [2.5, 7.5],
  CDP: [10, 15.2],
  GTEP: [17, 41],
};
const norm = (k: string, v: number | null | undefined, fallback: number) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return fallback;
  const [lo, hi] = NORM[k];
  return clamp01((v - lo) / (hi - lo));
};

export function useInvestigation(caseId: string | undefined) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(caseId));
  useEffect(() => {
    if (!caseId) {
      setInv(null);
      setLoading(false);
      return;
    }
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    getInvestigation(caseId, ac.signal)
      .then((r) => setInv(r))
      .catch((e) => {
        if (!ac.signal.aborted) setError(errorMessage(e));
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [caseId]);
  return { inv, error, loading };
}

export interface TwinDataOptions {
  thermalScenario: "none" | "T01_HOT_CONNECTION";
}

export function useTwinData(investigation: Investigation | null, win: TwinWindow, opts: TwinDataOptions): Omit<TwinData, "investigation"> {
  const [state, setState] = useState<Omit<TwinData, "investigation" | "window">>({
    loading: true,
    errors: [],
    series: null,
    thermal: null,
    emissions: null,
    personas: null,
    workRequests: [],
  });
  const key = `${win.year}|${win.start}|${win.end}|${investigation?.case_id ?? ""}|${opts.thermalScenario}`;

  useEffect(() => {
    const ac = new AbortController();
    const errors: string[] = [];
    const note = (what: string) => (e: unknown) => {
      if (!ac.signal.aborted) errors.push(`${what}: ${errorMessage(e)}`);
      return null;
    };
    const limit = Math.max(1, Math.min(MAX_WINDOW, win.end - win.start));
    setState((s) => ({ ...s, loading: true }));

    const seriesP = Promise.all(
      TWIN_MEASURES.map((m) =>
        getSeries(DATASET_ID, { measure: m, year: win.year, start: win.start, limit, include_expected: m === "TEY" }, ac.signal).catch(
          note(`series ${m}`),
        ),
      ),
    );
    const synthetic = investigation?.scenario_label === "synthetic_overlay";
    const overlayP =
      synthetic && investigation
      ? previewScenario(
          {
            dataset_id: DATASET_ID,
            scenario_id: investigation.scenario.scenario_id,
            year: win.year,
            start_index: win.start,
            end_index: win.end,
            seed: investigation.request.seed,
          },
          ac.signal,
        ).catch(note("synthetic overlay"))
      : Promise.resolve(null);
    const thermalP = evaluateThermal({ year: win.year, start: win.start, end: win.end, scenario: opts.thermalScenario }, ac.signal).catch(
      note("thermal model"),
    );
    const emissionsP = getEmissionsWindow({ year: win.year, start: win.start, end: win.end }, ac.signal).catch(note("emissions"));
    const personasP = getPersonas(ac.signal).catch(note("personas"));
    const wrP = investigation
      ? listWorkRequests({ case_id: investigation.case_id }, ac.signal).catch(note("work requests"))
      : Promise.resolve([] as WorkRequest[]);

    Promise.all([seriesP, overlayP, thermalP, emissionsP, personasP, wrP]).then(([series, overlay, thermal, emissions, personas, wrs]) => {
      if (ac.signal.aborted) return;
      setState({
        loading: false,
        errors,
        series: buildSeries(series, overlay),
        thermal,
        emissions,
        personas,
        workRequests: wrs ?? [],
      });
    });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return useMemo(() => ({ ...state, window: win }), [state, win]);
}

function buildSeries(
  series: (SeriesResponse | null)[],
  overlay: Awaited<ReturnType<typeof previewScenario>> | null,
): TwinSeries | null {
  const base = series.find((s) => s && s.points.length > 0);
  if (!base) return null;
  const rows = base.points.map((p) => p.row_index);
  const values: Record<string, (number | null)[]> = {};
  const units: Record<string, string> = {};
  let expectedTey: (number | null)[] = rows.map(() => null);
  series.forEach((s, i) => {
    const m = TWIN_MEASURES[i];
    if (!s) return;
    units[m] = s.unit;
    const byRow = new Map(s.points.map((p) => [p.row_index, p]));
    values[m] = rows.map((r) => byRow.get(r)?.value ?? null);
    if (m === "TEY") expectedTey = rows.map((r) => byRow.get(r)?.expected ?? null);
  });
  const syntheticMeasures: string[] = [];
  if (overlay?.synthetic) {
    for (const ss of overlay.series) {
      const byRow = new Map(ss.overlay.map((p) => [p.row_index, p.value]));
      if (!values[ss.measure]) continue;
      values[ss.measure] = rows.map((r, i) => (byRow.has(r) ? (byRow.get(r) ?? null) : values[ss.measure][i]));
      syntheticMeasures.push(ss.measure);
    }
  }
  return { rows, values, expectedTey, units, downsample: base.downsample_factor, syntheticMeasures };
}

/** Thermal series lookup: nearest sample at or before `row`. */
function thermalAt(thermal: ThermalEvaluateResponse | null, row: number) {
  if (!thermal || thermal.series.length === 0) return null;
  const s = thermal.series;
  let lo = 0;
  let hi = s.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (s[mid].row_index <= row) lo = mid;
    else hi = mid - 1;
  }
  return s[lo];
}

const ASSETS: AssetId[] = ["GEN", "GCB", "GSU", "HVSG", "BUS"];

/** Write the sample at `row` (with raw values `v`) into the mutable live state. */
export function fillLive(
  live: LiveState,
  row: number | null,
  v: Record<string, number | null>,
  thermal: ThermalEvaluateResponse | null,
  emissions: EmissionsResponse | null,
) {
  live.row = row;
  live.v = v;
  const co = v.CO;
  const nox = v.NOX;
  const coThr = emissions?.thresholds.co ?? 4.8;
  const noxThr = emissions?.thresholds.nox ?? 80;
  live.n = {
    tey: norm("TEY", v.TEY, 0.6),
    tit: norm("TIT", v.TIT, 0.6),
    afdp: norm("AFDP", v.AFDP, 0.3),
    cdp: norm("CDP", v.CDP, 0.5),
    gtep: norm("GTEP", v.GTEP, 0.5),
    co: co === null || co === undefined ? 0.2 : clamp01((co / coThr) * 0.7),
    nox: nox === null || nox === undefined ? 0.4 : clamp01((nox / noxThr) * 0.7),
  };
  const t = row === null ? null : thermalAt(thermal, row);
  live.temps = {};
  live.heat = {};
  if (t && thermal) {
    for (const a of ASSETS) {
      const temp = t[a];
      live.temps[a] = temp;
      const alarm = thermal.status.find((s) => s.asset_id === a)?.alarm_c ?? 100;
      live.heat[a] = clamp01((temp - t.ambient_c) / Math.max(1, alarm - t.ambient_c));
    }
  }
}

export function sampleAt(series: TwinSeries | null, i: number): { row: number | null; v: Record<string, number | null>; expectedTey: number | null } {
  if (!series || series.rows.length === 0) return { row: null, v: {}, expectedTey: null };
  const k = Math.min(series.rows.length - 1, Math.max(0, i));
  const v: Record<string, number | null> = {};
  for (const m of Object.keys(series.values)) v[m] = series.values[m][k];
  return { row: series.rows[k], v, expectedTey: series.expectedTey[k] ?? null };
}

export function thermalTempsAt(thermal: ThermalEvaluateResponse | null, row: number | null) {
  return row === null ? null : thermalAt(thermal, row);
}

/** Optional SIMULATED historian replay: polls the latest replayed row every `ms`. */
export function useHistorian(enabled: boolean, ms = 2000) {
  const [data, setData] = useState<HistorianLatest | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
      return;
    }
    let alive = true;
    const ac = new AbortController();
    const tick = () =>
      getHistorianLatest(1, ac.signal)
        .then((d) => {
          if (alive) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => {
          if (alive) setError(errorMessage(e));
        });
    void tick();
    const id = window.setInterval(tick, ms);
    return () => {
      alive = false;
      ac.abort();
      window.clearInterval(id);
    };
  }, [enabled, ms]);
  return { data, error };
}
