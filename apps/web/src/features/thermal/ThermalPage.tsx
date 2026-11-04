import { AlertTriangle, FlaskConical, Info, ShieldAlert, Thermometer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";
import { getDataset, listDatasets } from "../../api/client";
import { ChartSkeleton, ErrorBanner, PanelSkeleton, WarnBanner } from "../../components/Feedback";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtInt, fmtNum, sampleLabel } from "../../lib/format";
import { evaluateThermal, getThermalAssets } from "./api";
import { STATE_STYLE, ThermalMap } from "./ThermalMap";
import type {
  AssetId,
  AssetStatus,
  DemandProfile,
  Severity,
  ThermalAssumptions,
  ThermalEvaluateRequest,
  ThermalEvaluateResponse,
} from "./types";

const DATASET_ID = "ds_uci_551";
const BANNER =
  "Simulated thermal feed derived from real load and ambient data — no thermal sensors are connected; advisory only; no load or breaker is changed by this software.";

/** Validated with the dataviz palette checker (blue measured-derived vs yellow-700 what-if overlay, light surface). */
const C = { feed: "#2563eb", whatif: "#a16207", alarm: "#ca8a04", limit: "#dc2626", grid: "#e2e6ec", axis: "#cbd5e1" };

type KeyAssumption = keyof ThermalAssumptions;
const KEY_ASSUMPTIONS: { key: KeyAssumption; label: string; unit: string }[] = [
  { key: "generator_rated_mwh", label: "Generator rating", unit: "MWh/h-sample" },
  { key: "transformer_rated_mwh", label: "Transformer rating", unit: "MWh/h-sample" },
  { key: "hv_rated_mwh", label: "HV switchgear/busbar rating", unit: "MWh/h-sample" },
  { key: "indoor_ambient_offset_k", label: "Enclosure above outdoor AT", unit: "K" },
  { key: "approach_margin_k", label: "Approach band below alarm", unit: "K" },
  { key: "top_oil_rise_rated_k", label: "Δθ top-oil rise at rated", unit: "K" },
  { key: "hot_spot_gradient_rated_k", label: "Δθ hot-spot gradient at rated", unit: "K" },
  { key: "transformer_hot_spot_alarm_c", label: "Transformer hot-spot alarm", unit: "°C" },
  { key: "transformer_hot_spot_limit_c", label: "Transformer hot-spot limit", unit: "°C" },
  { key: "contact_alarm_c", label: "Contact alarm (GCB, HVSG)", unit: "°C" },
  { key: "contact_limit_c", label: "Contact limit (GCB, HVSG)", unit: "°C" },
  { key: "busbar_alarm_c", label: "Busbar alarm", unit: "°C" },
];

const SEV_STYLE: Record<Severity, string> = {
  info: "border-ink-600 bg-white text-ink-200",
  watch: "border-yellow-400 bg-yellow-50 text-yellow-900",
  warning: "border-amber-400 bg-amber-50 text-amber-900",
  high: "border-red-300 bg-red-50 text-red-900",
};

function AssumptionBadge() {
  return (
    <span
      title="Assumption input — not a measurement; confirm with equipment data"
      className="inline-flex items-center whitespace-nowrap rounded-md border border-blue-300 bg-blue-50 px-1.5 py-px text-xs font-semibold tracking-wide text-blue-800"
    >
      ASSUMPTION
    </span>
  );
}

function SyntheticBadge() {
  return <SourceBadge variant="synthetic" size="sm" label="SYNTHETIC" />;
}

function WhatIfBadge() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-md border border-dashed border-yellow-500 bg-white px-1.5 py-px text-xs font-semibold tracking-wide text-yellow-900">
      WHAT-IF
    </span>
  );
}

function intOr(s: string): number | null {
  if (s.trim() === "") return null;
  const v = Number(s);
  return Number.isInteger(v) && v >= 0 ? v : null;
}

function TipBox({ active, payload, label, year, unit }: TooltipProps<number, string> & { year: number; unit: string }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-white px-3 py-2 text-sm shadow-lg">
      <div className="mb-1 font-mono text-ink-300">{sampleLabel(year, Number(label))}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />
          <span className="text-ink-300">{p.name}</span>
          <span className="ml-auto font-mono text-ink-50">
            {fmtNum(p.value as number, unit === "%" ? 5 : 1)} <span className="text-ink-400">{unit}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function Legend({ items }: { items: { name: string; color: string; dashed?: boolean; tag?: ReactNode }[] }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-300">
      {items.map((s) => (
        <span key={s.name} className="inline-flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="22" y2="4" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? "5 3" : undefined} />
          </svg>
          {s.name}
          {s.tag}
        </span>
      ))}
    </div>
  );
}

function TemperatureChart({ data, asset, status, year }: { data: ThermalEvaluateResponse; asset: AssetId; status: AssetStatus; year: number }) {
  const showWhatIf = asset === "GSU" && data.demand.applied;
  const rows = data.series.map((p) => ({ row_index: p.row_index, temp: p[asset], whatif: showWhatIf ? p.GSU_whatif : null }));
  const vals = rows.flatMap((r) => [r.temp, r.whatif ?? r.temp]);
  const lo = Math.floor((Math.min(...vals) - 5) / 10) * 10;
  const hi = Math.ceil(Math.max(status.limit_c + 5, ...vals) / 10) * 10;
  const label = asset === "GSU" ? "hot-spot" : status.name.toLowerCase();
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title">
            {status.name} {asset === "GSU" ? "hot-spot" : "temperature"} vs alarm / limit
          </div>
          <Legend
            items={[
              { name: `${label} (simulated)`, color: C.feed, tag: status.synthetic ? <SyntheticBadge /> : null },
              ...(showWhatIf ? [{ name: `hot-spot, demand ×${fmtNum(data.demand.multiplier, 2)}`, color: C.whatif, dashed: true, tag: <WhatIfBadge /> }] : []),
              { name: `alarm ${fmtNum(status.alarm_c, 0)} °C`, color: C.alarm, dashed: true, tag: <AssumptionBadge /> },
              { name: `limit ${fmtNum(status.limit_c, 0)} °C`, color: C.limit, dashed: true, tag: <AssumptionBadge /> },
            ]}
          />
        </div>
        <SourceBadge variant="model" size="sm" label="SIMULATED FROM REAL LOAD" />
      </div>
      <div className="px-2 pb-2 pt-4" style={{ height: 284 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="row_index"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickCount={8}
              stroke={C.axis}
              tickLine={false}
              height={40}
              label={{ value: "sample index (ordered hourly samples, no timestamps)", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 12 }}
            />
            <YAxis domain={[lo, hi]} tickCount={Math.min(9, (hi - lo) / 10 + 1)} stroke={C.axis} tickLine={false} width={56} label={{ value: "°C", angle: -90, position: "insideLeft", offset: 12, fill: "#64748b", fontSize: 12 }} />
            <Tooltip content={(p) => <TipBox {...(p as TooltipProps<number, string>)} year={year} unit="°C" />} isAnimationActive={false} />
            <ReferenceLine y={status.alarm_c} stroke={C.alarm} strokeDasharray="6 4" strokeWidth={1.5} />
            <ReferenceLine y={status.limit_c} stroke={C.limit} strokeDasharray="6 4" strokeWidth={1.5} />
            <Line type="monotone" dataKey="temp" name={`${label} (simulated)`} stroke={C.feed} strokeWidth={2} dot={false} isAnimationActive={false} />
            {showWhatIf ? (
              <Line type="monotone" dataKey="whatif" name="hot-spot what-if" stroke={C.whatif} strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
        Points are bucket maxima (downsample ×{data.downsample_factor}). Planning model, not a measurement.
      </div>
    </div>
  );
}

function LossOfLifeChart({ data, year }: { data: ThermalEvaluateResponse; year: number }) {
  const showWhatIf = data.demand.applied;
  const rows = data.series.map((p) => ({ row_index: p.row_index, lol: p.lol_cum_pct, whatif: showWhatIf ? p.lol_cum_pct_whatif : null }));
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title">Step-up transformer cumulative loss of life (IEEE C57.91 ageing model)</div>
          <Legend
            items={[
              { name: "cumulative loss of life (simulated)", color: C.feed },
              ...(showWhatIf ? [{ name: `demand ×${fmtNum(data.demand.multiplier, 2)}`, color: C.whatif, dashed: true, tag: <WhatIfBadge /> }] : []),
            ]}
          />
        </div>
        <SourceBadge variant="model" size="sm" label="MODEL-DERIVED" />
      </div>
      <div className="px-2 pb-2 pt-4" style={{ height: 244 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="row_index" type="number" domain={["dataMin", "dataMax"]} tickCount={8} stroke={C.axis} tickLine={false} height={40}
              label={{ value: "sample index (no timestamps)", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 12 }} />
            <YAxis stroke={C.axis} tickLine={false} width={72} tickFormatter={(v: number) => fmtNum(v, 4)}
              label={{ value: "% of life", angle: -90, position: "insideLeft", offset: 4, fill: "#64748b", fontSize: 12 }} />
            <Tooltip content={(p) => <TipBox {...(p as TooltipProps<number, string>)} year={year} unit="%" />} isAnimationActive={false} />
            <Line type="monotone" dataKey="lol" name="loss of life" stroke={C.feed} strokeWidth={2} dot={false} isAnimationActive={false} />
            {showWhatIf ? <Line type="monotone" dataKey="whatif" name="loss of life what-if" stroke={C.whatif} strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} /> : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
        F_AA = exp(15000/383 − 15000/(θ_H+273)); normal insulation life {fmtInt(data.ageing.normal_insulation_life_h)} h (assumption).
      </div>
    </div>
  );
}

export default function ThermalPage() {
  const datasets = useAsync((s) => listDatasets(s), []);
  const assets = useAsync((s) => getThermalAssets(s), []);
  const detail = useAsync((s) => getDataset(DATASET_ID, s), []);
  const years = useMemo(() => {
    const ds = datasets.data?.find((d) => d.dataset_id === DATASET_ID) ?? datasets.data?.[0];
    return ds?.years ?? [2011, 2012, 2013, 2014, 2015];
  }, [datasets.data]);

  const [year, setYear] = useState(2014);
  const [startText, setStartText] = useState("1200");
  const [endText, setEndText] = useState("1320");
  const [hotConnection, setHotConnection] = useState(false);
  const [multiplier, setMultiplier] = useState(1.0);
  const [profile, setProfile] = useState<DemandProfile>("flat");
  const [assumptionText, setAssumptionText] = useState<Partial<Record<KeyAssumption, string>>>({});
  const [selected, setSelected] = useState<AssetId>("GSU");
  const [mapView, setMapView] = useState<"baseline" | "whatif">("baseline");

  const defaults = assets.data?.default_assumptions;
  const start = intOr(startText);
  const end = intOr(endText);
  const windowInvalid = start === null || end === null || end - start < 24;
  const parsedAssumptions = useMemo(() => {
    const out: Partial<ThermalAssumptions> = {};
    const bad: KeyAssumption[] = [];
    for (const { key } of KEY_ASSUMPTIONS) {
      const t = assumptionText[key];
      if (t === undefined || t.trim() === "") continue;
      const v = Number(t);
      if (Number.isFinite(v) && v > 0) out[key] = v;
      else bad.push(key);
    }
    return { out, bad };
  }, [assumptionText]);

  const request: ThermalEvaluateRequest | null = useMemo(() => {
    if (windowInvalid || parsedAssumptions.bad.length > 0 || start === null || end === null) return null;
    return {
      dataset_id: DATASET_ID,
      year,
      start,
      end,
      assumptions: parsedAssumptions.out,
      scenario: hotConnection ? "T01_HOT_CONNECTION" : "none",
      demand_multiplier: Math.abs(multiplier - 1) > 1e-9 ? multiplier : null,
      demand_profile: profile,
    };
  }, [windowInvalid, parsedAssumptions, start, end, year, hotConnection, multiplier, profile]);

  const [applied, setApplied] = useState<string | null>(null);
  const requestKey = request ? JSON.stringify(request) : null;
  useEffect(() => {
    if (requestKey === null) return;
    const t = window.setTimeout(() => setApplied(requestKey), 400);
    return () => window.clearTimeout(t);
  }, [requestKey]);

  const result = useAsync<ThermalEvaluateResponse | null>(
    (s) => (applied ? evaluateThermal(JSON.parse(applied) as ThermalEvaluateRequest, s) : Promise.resolve(null)),
    [applied],
  );
  const data = result.data;

  useEffect(() => {
    if (!data?.demand.applied) setMapView("baseline");
  }, [data?.demand.applied]);

  const mapStatus = data ? (mapView === "whatif" && data.demand.applied ? data.demand.scenario_status : data.status) : [];
  const selStatus = data?.status.find((s) => s.asset_id === selected) ?? null;
  const gsu = data?.status.find((s) => s.asset_id === "GSU") ?? null;
  const tightest = data ? [...data.status].sort((a, b) => a.margin_to_alarm_k - b.margin_to_alarm_k)[0] : null;
  const dataYear = data?.window.source_year ?? year;

  return (
    <div>
      <PageHeader
        title="Thermal monitoring — electrical balance of plant"
        subtitle="Generator, generator breaker, step-up transformer, HV switchgear and busbar: simulated temperatures, margins to alarm, transformer ageing and read-only advisories."
      />
      <div className="-mt-3 mb-4 flex flex-wrap items-center gap-2">
        <SourceBadge variant="real" label="REAL LOAD + AMBIENT (TEY, AT)" size="sm" />
        <SourceBadge variant="model" label="SIMULATED THERMAL FEED" size="sm" />
        {data?.synthetic ? <SourceBadge variant="synthetic" size="sm" label="SYNTHETIC DEFECT" /> : null}
        <SourceBadge variant="review" size="sm" label="ADVISORY ONLY" />
      </div>

      <WarnBanner className="mb-5" icon={<ShieldAlert size={20} />}>
        <span className="font-semibold">{BANNER}</span>
      </WarnBanner>

      {/* controls */}
      <div className="panel mb-5 p-5">
        <div className="flex flex-wrap items-end gap-5">
          <label className="flex flex-col gap-1.5">
            <span className="label">Year</span>
            <select className="input w-28" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">Start sample</span>
            <input className={`input w-28 font-mono ${start === null ? "border-red-400" : ""}`} inputMode="numeric" value={startText} onChange={(e) => setStartText(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">End sample (excl.)</span>
            <input className={`input w-28 font-mono ${end === null ? "border-red-400" : ""}`} inputMode="numeric" value={endText} onChange={(e) => setEndText(e.target.value)} />
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-secondary h-10 px-3 text-sm" onClick={() => { setStartText("1200"); setEndText("1320"); }}>
              Default window
            </button>
            <button
              type="button"
              className="btn-secondary h-10 px-3 text-sm"
              onClick={() => {
                const n = detail.data?.rows_per_year?.[String(year)];
                setStartText("0");
                setEndText(String(n ?? 7158));
              }}
            >
              Whole year
            </button>
          </div>
          <label className="flex items-center gap-2 rounded-lg border border-yellow-300 bg-yellow-50 px-3 py-2">
            <input type="checkbox" checked={hotConnection} onChange={(e) => setHotConnection(e.target.checked)} />
            <FlaskConical size={16} className="text-yellow-800" />
            <span className="text-sm font-semibold text-yellow-900">T01 hot connection</span>
            <SyntheticBadge />
          </label>
        </div>
        {windowInvalid ? <div className="mt-2 text-sm text-red-700">Window needs whole-number start/end with at least 24 samples.</div> : null}

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div className="rounded-lg border border-ink-700 p-4">
            <div className="label flex items-center gap-2">
              Data-center demand growth scenario <WhatIfBadge />
            </div>
            <div className="mt-2 flex items-center gap-3">
              <input
                type="range"
                min={1}
                max={1.5}
                step={0.01}
                value={multiplier}
                onChange={(e) => setMultiplier(Number(e.target.value))}
                className="w-full accent-yellow-600"
                aria-label="demand multiplier"
              />
              <span className="w-20 text-right font-mono text-lg font-semibold text-ink-50">×{multiplier.toFixed(2)}</span>
            </div>
            <div className="mt-1 text-sm text-ink-300">
              {multiplier > 1 ? `What if data-center demand raised our dispatch by ${Math.round((multiplier - 1) * 100)} %?` : "Off (×1.00). Drag to add demand."}
            </div>
            <div className="mt-3 flex gap-3 text-sm">
              {(["flat", "diurnal_datacenter"] as DemandProfile[]).map((p) => (
                <label key={p} className="inline-flex items-center gap-1.5">
                  <input type="radio" name="profile" checked={profile === p} onChange={() => setProfile(p)} />
                  {p === "flat" ? "flat" : "diurnal data-center ramp"}
                </label>
              ))}
            </div>
            {profile === "diurnal_datacenter" ? (
              <div className="mt-2 text-xs text-ink-400">Notional hour = sample index mod 24 — UCI rows have no timestamps; not a clock time.</div>
            ) : null}
          </div>

          <div className="rounded-lg border border-ink-700 p-4">
            <div className="label mb-2 flex items-center gap-2">
              Key assumptions <AssumptionBadge /> <span className="font-normal normal-case text-ink-400">blank = default</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {KEY_ASSUMPTIONS.map(({ key, label, unit }) => {
                const bad = parsedAssumptions.bad.includes(key);
                return (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-xs text-ink-300">{label}</span>
                    <div className="flex items-center gap-1.5">
                      <input
                        className={`input h-9 w-24 font-mono text-sm ${bad ? "border-red-400" : ""}`}
                        inputMode="decimal"
                        placeholder={defaults ? String(defaults[key]) : ""}
                        value={assumptionText[key] ?? ""}
                        onChange={(e) => setAssumptionText((prev) => ({ ...prev, [key]: e.target.value }))}
                      />
                      <span className="text-xs text-ink-400">{unit}</span>
                    </div>
                  </label>
                );
              })}
            </div>
            {parsedAssumptions.bad.length > 0 ? <div className="mt-2 text-sm text-red-700">Assumptions must be numbers &gt; 0.</div> : null}
          </div>
        </div>
      </div>

      {result.error ? <ErrorBanner className="mb-5" error={result.error} title="Thermal evaluation failed" onRetry={result.reload} /> : null}

      {!data && !result.error ? (
        <div className="grid gap-5">
          <PanelSkeleton lines={5} />
          <ChartSkeleton />
        </div>
      ) : null}

      {data ? (
        <div className="grid gap-5">
          {/* map */}
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">One-line thermal map</div>
                <div className="mt-1 text-sm text-ink-300">
                  {dataYear} • samples #{data.window.start}–#{data.window.end - 1} ({fmtInt(data.window.n_samples)} hourly samples). Click an asset to chart it.
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {data.demand.applied ? (
                  <div className="inline-flex overflow-hidden rounded-md border border-ink-600 text-sm">
                    {(["baseline", "whatif"] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => setMapView(v)}
                        className={`px-3 py-1 ${mapView === v ? "bg-blue-600 text-white" : "bg-white text-ink-200"}`}
                      >
                        {v === "baseline" ? "Baseline" : `What-if ×${fmtNum(data.demand.multiplier, 2)}`}
                      </button>
                    ))}
                  </div>
                ) : null}
                {Object.entries(STATE_STYLE).map(([k, s]) => (
                  <span key={k} className="inline-flex items-center gap-1 text-xs text-ink-300">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm border" style={{ background: s.fill, borderColor: s.stroke }} />
                    {s.label.toLowerCase()}
                  </span>
                ))}
              </div>
            </div>
            <div className="px-3 py-3">
              <ThermalMap
                status={mapStatus}
                syntheticAssetId={data.synthetic_defect?.asset_id ?? null}
                whatIf={mapView === "whatif" && data.demand.applied}
                selected={selected}
                onSelect={setSelected}
              />
            </div>
            {data.synthetic_defect ? (
              <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-yellow-900">
                <SyntheticBadge /> <span className="ml-1">{data.synthetic_defect.description}</span>
              </div>
            ) : null}
          </div>

          {/* KPIs */}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Transformer hot-spot (simulated)"
              value={fmtNum(gsu?.current_c, 1)}
              unit="°C"
              icon={<Thermometer size={16} />}
              caption={gsu ? `top oil ${fmtNum(gsu.top_oil_c, 1)} °C · ${fmtNum(gsu.margin_to_alarm_k, 1)} K to alarm` : undefined}
            />
            <KpiCard
              label="Tightest margin to alarm"
              value={fmtNum(tightest?.margin_to_alarm_k, 1)}
              unit="K"
              tone={tightest && tightest.state !== "normal" ? "amber" : "default"}
              caption={tightest ? `${tightest.name} · ${STATE_STYLE[tightest.state].label.toLowerCase()}` : undefined}
            />
            <KpiCard
              label="Ageing factor F_EQA (window)"
              value={fmtNum(data.ageing.equivalent_faa, 4)}
              tone="model"
              caption={`now ${fmtNum(data.ageing.current_faa, 4)} · 1.0 = normal ageing at 110 °C`}
            />
            <KpiCard
              label="Loss of life (window)"
              value={fmtNum(data.ageing.loss_of_life_pct, 5)}
              unit="%"
              tone="model"
              caption={`${fmtNum(data.ageing.loss_of_life_h, 2)} h equivalent · extrapolated ${fmtNum(data.ageing.extrapolated_loss_of_life_pct_per_year, 3)} %/yr (EXTRAPOLATED)`}
            />
          </div>

          {/* charts */}
          <div className="flex flex-wrap gap-2">
            {data.status.map((s) => (
              <button
                key={s.asset_id}
                type="button"
                onClick={() => setSelected(s.asset_id)}
                className={`chip ${selected === s.asset_id ? "border-blue-500 bg-blue-50 text-blue-800" : ""}`}
              >
                {s.name}
              </button>
            ))}
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            {selStatus ? <TemperatureChart data={data} asset={selected} status={selStatus} year={dataYear} /> : null}
            <LossOfLifeChart data={data} year={dataYear} />
          </div>

          {/* demand impact */}
          {data.demand.applied ? (
            <div className="panel">
              <div className="panel-header">
                <div>
                  <div className="panel-title flex items-center gap-2">
                    Demand scenario impact — ×{fmtNum(data.demand.multiplier, 2)} {data.demand.profile === "flat" ? "flat" : "diurnal data-center ramp"} <WhatIfBadge />
                  </div>
                  <div className="mt-1 text-sm text-ink-300">
                    Samples above nameplate (K &gt; 1): {fmtInt(data.demand.samples_above_nameplate_baseline)} → {fmtInt(data.demand.samples_above_nameplate_scenario)} ·
                    transformer loss of life {fmtNum(data.demand.baseline_loss_of_life_pct, 5)} % → {fmtNum(data.demand.scenario_loss_of_life_pct, 5)} %
                  </div>
                </div>
              </div>
              <div className="overflow-x-auto px-5 py-3">
                <table className="w-full min-w-[560px] text-sm">
                  <thead>
                    <tr className="text-left text-ink-400">
                      <th className="py-1.5 pr-3 font-semibold">Asset</th>
                      <th className="py-1.5 pr-3 text-right font-semibold">Peak baseline</th>
                      <th className="py-1.5 pr-3 text-right font-semibold">Peak what-if</th>
                      <th className="py-1.5 pr-3 text-right font-semibold">Δ peak</th>
                      <th className="py-1.5 pr-3 text-right font-semibold">Samples ≥ alarm</th>
                      <th className="py-1.5 text-right font-semibold">Samples ≥ limit</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {data.demand.impact.map((r) => (
                      <tr key={r.asset_id} className="border-t border-ink-700">
                        <td className="py-1.5 pr-3 font-sans">{data.status.find((s) => s.asset_id === r.asset_id)?.name}</td>
                        <td className="py-1.5 pr-3 text-right">{fmtNum(r.baseline_peak_c, 1)} °C</td>
                        <td className="py-1.5 pr-3 text-right">{fmtNum(r.scenario_peak_c, 1)} °C</td>
                        <td className="py-1.5 pr-3 text-right">+{fmtNum(r.delta_peak_k, 1)} K</td>
                        <td className={`py-1.5 pr-3 text-right ${r.scenario_samples_above_alarm > 0 ? "font-semibold text-amber-800" : ""}`}>
                          {r.baseline_samples_above_alarm} → {r.scenario_samples_above_alarm}
                        </td>
                        <td className={`py-1.5 text-right ${r.scenario_samples_above_limit > 0 ? "font-semibold text-red-700" : ""}`}>
                          {r.baseline_samples_above_limit} → {r.scenario_samples_above_limit}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
                {data.demand.caveat}
                {data.demand.notional_hour_note ? ` ${data.demand.notional_hour_note}.` : ""}
              </div>
            </div>
          ) : null}

          {/* flags + advisories */}
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">Screening flags ({data.flags.length})</div>
              </div>
              <div className="px-5 py-3">
                {data.flags.length === 0 ? (
                  <div className="flex items-center gap-2 text-base text-ink-300">
                    <Info size={16} /> No screening flags in this window at these assumptions.
                  </div>
                ) : (
                  <ul className="grid gap-2">
                    {data.flags.map((f, i) => (
                      <li key={i} className={`rounded-lg border px-3 py-2 text-sm ${SEV_STYLE[f.severity]}`}>
                        <div className="flex flex-wrap items-center gap-2 font-semibold">
                          <AlertTriangle size={14} /> {f.flag.replace(/_/g, " ")} · {f.asset_id} · {f.severity}
                          {f.synthetic ? <SyntheticBadge /> : null}
                        </div>
                        <div className="mt-0.5">{f.message}</div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title flex items-center gap-2">
                  Advisories ({data.advisories.length}) <SourceBadge variant="review" size="sm" label="READ-ONLY · HUMAN DECISION" />
                </div>
              </div>
              <div className="px-5 py-3">
                {data.advisories.length === 0 ? (
                  <div className="flex items-center gap-2 text-base text-ink-300">
                    <Info size={16} /> No advisories — all simulated temperatures are outside the approach band.
                  </div>
                ) : (
                  <ul className="grid gap-2">
                    {data.advisories.map((a, i) => (
                      <li key={i} className={`rounded-lg border px-3 py-2 text-sm ${SEV_STYLE[a.severity]}`}>
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                          {a.asset_id} · {a.kind.replace(/_/g, " ")} · {a.severity}
                          {a.synthetic ? <SyntheticBadge /> : null}
                          {a.what_if ? <WhatIfBadge /> : null}
                        </div>
                        {a.text}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>

          {/* status table */}
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">Asset status (last sample of the window)</div>
            </div>
            <div className="overflow-x-auto px-5 py-3">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-left text-ink-400">
                    <th className="py-1.5 pr-3 font-semibold">Asset</th>
                    <th className="py-1.5 pr-3 font-semibold">State</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">Now</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">K</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">To alarm</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">To limit</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">Peak</th>
                    <th className="py-1.5 pr-3 text-right font-semibold">Trend (24)</th>
                    <th className="py-1.5 text-right font-semibold">Rise index</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {data.status.map((s) => (
                    <tr key={s.asset_id} className="border-t border-ink-700">
                      <td className="py-1.5 pr-3 font-sans">
                        {s.name} {s.synthetic ? <SyntheticBadge /> : null}
                      </td>
                      <td className="py-1.5 pr-3 font-sans text-xs font-semibold" style={{ color: STATE_STYLE[s.state].text }}>
                        {STATE_STYLE[s.state].label}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.current_c, 1)} °C</td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.load_ratio_k, 3)}</td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.margin_to_alarm_k, 1)} K</td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.margin_to_limit_k, 1)} K</td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.peak_c, 1)} °C</td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.trend_k_per_sample, 3)} K/s</td>
                      <td className="py-1.5 text-right">{s.rise_index === null ? "—" : fmtNum(s.rise_index, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
              {data.model_note} K = TEY / rating (MWh per hourly sample, as published). Rise index = load-corrected rise ÷ rated rise
              (1.0 = healthy I²R behaviour). Provenance: <span className="font-mono">{data.provenance}</span>.
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
