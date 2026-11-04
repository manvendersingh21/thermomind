import { AlertOctagon, BookOpen, Gauge, Network, PlayCircle, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import { ErrorBanner, InfoBanner, PanelSkeleton, Spinner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SERIES_COLORS, SeriesChart } from "../../components/SeriesChart";
import type { ChartRow } from "../../components/SeriesChart";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtNum, humanize } from "../../lib/format";
import { getContingency, getReadiness, runDrill } from "./api";
import type {
  CardStatus,
  ContingencyConstraint,
  ContingencyResult,
  GridDrill,
  GridEvent,
  GridNumber,
  GridProvenance,
  ReadinessQuery,
  StatusCard,
  TopologyNode,
} from "./types";

const DATASET_ID = "ds_uci_551";
const BANNER = "Synthetic drill. Advisory only. This software issues no control actions.";

function ProvBadge({ p }: { p: GridProvenance }) {
  if (p === "real_observation") return <SourceBadge variant="real" size="sm" label="REAL" />;
  if (p === "model_derived") return <SourceBadge variant="model" size="sm" />;
  if (p === "synthetic_overlay") return <SourceBadge variant="synthetic" size="sm" />;
  if (p === "simulated") return <SourceBadge variant="offline" size="sm" label="SIMULATED" />;
  return <AssumptionBadge />;
}

function AssumptionBadge() {
  return (
    <span className="inline-flex items-center rounded-md border border-dashed border-yellow-500 bg-yellow-50 px-2 py-0.5 text-xs font-semibold tracking-wide text-yellow-900">
      ASSUMPTION
    </span>
  );
}

const STATUS_STYLE: Record<CardStatus, { cls: string; label: string }> = {
  ok: { cls: "border-t-green-500", label: "OK" },
  info: { cls: "border-t-blue-600", label: "INFO" },
  watch: { cls: "border-t-yellow-400", label: "WATCH" },
  limited: { cls: "border-t-red-500", label: "LIMITED" },
};

function StatusPillSmall({ s }: { s: CardStatus }) {
  const cls =
    s === "ok"
      ? "bg-green-50 text-green-800 border-green-300"
      : s === "watch"
        ? "bg-yellow-100 text-yellow-900 border-yellow-400"
        : s === "limited"
          ? "bg-red-50 text-red-800 border-red-300"
          : "bg-blue-50 text-blue-800 border-blue-300";
  return <span className={`rounded-md border px-2 py-0.5 text-xs font-bold tracking-wide ${cls}`}>{STATUS_STYLE[s].label}</span>;
}

function NumberRow({ n }: { n: GridNumber }) {
  return (
    <div className="border-b border-ink-800 py-1.5 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-ink-300">{n.label}</span>
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm text-ink-50">
            {n.value === null ? "—" : fmtNum(n.value, 2)} <span className="text-ink-400">{n.unit}</span>
          </span>
          <ProvBadge p={n.provenance} />
        </span>
      </div>
      <div className="mt-0.5 font-mono text-xs text-ink-400">{n.computation}</div>
      {n.note ? <div className="mt-0.5 text-xs text-ink-300">{n.note}</div> : null}
    </div>
  );
}

function ReadinessCard({ c }: { c: StatusCard }) {
  return (
    <div className={`panel border-t-2 px-5 py-4 ${STATUS_STYLE[c.status].cls}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="label">{c.title}</div>
        <StatusPillSmall s={c.status} />
      </div>
      <div className="mt-2 text-base font-semibold text-ink-50">{c.headline}</div>
      <div className="mt-2">
        {c.numbers.map((n) => (
          <NumberRow key={n.key} n={n} />
        ))}
      </div>
      {c.note ? <div className="mt-2 text-xs text-ink-400">{c.note}</div> : null}
    </div>
  );
}

function NumInput({
  label,
  value,
  onChange,
  step = 1,
  assumption = false,
  width = "w-28",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  assumption?: boolean;
  width?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-sm text-ink-300">
        {label} {assumption ? <AssumptionBadge /> : null}
      </span>
      <input
        type="number"
        className={`input ${width}`}
        value={Number.isFinite(value) ? value : ""}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function toRows(points: { row_index: number; value: number | null }[], key: string, constKey: string, constVal: number | null): ChartRow[] {
  return points.map((p) => ({ row_index: p.row_index, [key]: p.value, [constKey]: constVal }) as ChartRow);
}

function BriefList({ title, items, tone = "default" }: { title: string; items: string[]; tone?: "default" | "verify" }) {
  return (
    <div className={`panel px-5 py-4 ${tone === "verify" ? "border-l-4 border-l-blue-600" : ""}`}>
      <div className="label mb-2">{title}</div>
      <ul className="list-disc space-y-1.5 pl-5 text-base text-ink-100">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  );
}

function DrillResult({ d }: { d: GridDrill }) {
  const ev = d.evidence;
  const tey = d.series.find((s) => s.measure === "TEY");
  const rows: ChartRow[] = tey
    ? tey.original.map((p, i) => ({ row_index: p.row_index, original: p.value, overlay: tey.overlay[i]?.value ?? null }) as ChartRow)
    : [];
  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {d.mode === "meta_live" ? (
          <SourceBadge variant="meta" label={`META LIVE · ${d.meta_model ?? "muse-spark"}`} />
        ) : (
          <SourceBadge variant="offline" label={d.mode === "offline_fallback" ? "OFFLINE FALLBACK (deterministic)" : "OFFLINE PREVIEW (deterministic)"} />
        )}
        <SourceBadge variant="synthetic" label="SYNTHETIC OVERLAY · S05_GRID_EVENT" />
        <SourceBadge variant="review" />
        <span className="font-mono text-sm text-ink-400">{d.drill_id}</span>
      </div>
      <div className="panel px-5 py-4">
        <div className="label">Headline</div>
        <div className="mt-1 text-lg font-semibold text-ink-50">{d.brief.headline}</div>
        <div className="mt-2 font-mono text-xs text-ink-400">{ev.tey_computation}</div>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <BriefList title="What the data shows" items={d.brief.what_the_data_shows} />
        <BriefList title="Operator verifications (per grid code & site procedures)" items={d.brief.operator_verifications} tone="verify" />
        <BriefList title="Plant capability (assumption-based, not an instruction)" items={d.brief.plant_capability} />
        <BriefList title="Notify" items={d.brief.notify} />
        <BriefList title="Risks & limits" items={d.brief.risks} />
        <div className="panel px-5 py-4">
          <div className="label mb-2">Co-movement (synthetic, scaled from training-year slopes)</div>
          <table className="table-base">
            <thead>
              <tr>
                <th>Measure</th>
                <th className="text-right">Δ step</th>
                <th className="text-right">slope / MWh</th>
                <th className="text-right">r</th>
              </tr>
            </thead>
            <tbody>
              {ev.co_movement.map((c) => (
                <tr key={c.measure}>
                  <td>{c.measure}</td>
                  <td className="text-right font-mono">
                    {fmtNum(c.delta_overlay_vs_original, 3)} {c.unit.split(" ")[0]}
                  </td>
                  <td className="text-right font-mono">{fmtNum(c.train_slope_per_mwh, 4)}</td>
                  <td className="text-right font-mono">{fmtNum(c.train_r, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-xs text-ink-400">{ev.event_note}</div>
        </div>
      </div>
      <SeriesChart
        title="TEY: original copy vs synthetic S05 overlay"
        unit="MWh"
        year={ev.window.source_year}
        data={rows}
        height={200}
        series={[
          { key: "original", name: "TEY (real)", color: SERIES_COLORS.measured },
          { key: "overlay", name: "TEY + S05 overlay", color: SERIES_COLORS.overlay, dashed: true, tag: "SYNTHETIC" },
        ]}
        highlight={{ start: ev.step_samples.start, end: ev.step_samples.end, label: "synthetic step" }}
      />
      <div className="panel px-5 py-3 text-sm text-ink-300">
        <div className="label mb-1">Disclaimer</div>
        {d.brief.disclaimer}
        {d.validation_errors.length ? (
          <div className="mt-2 font-mono text-xs text-amber-800">validation: {d.validation_errors.join(" | ")}</div>
        ) : null}
        <div className="mt-2 font-mono text-xs text-ink-400">
          {d.events.map((e) => `${e.seq}. ${e.kind}${e.latency_ms ? ` (${e.latency_ms} ms)` : ""}`).join(" · ")}
        </div>
      </div>
    </div>
  );
}

function SingleLine({ topo, constraint }: { topo: TopologyNode[]; constraint: ContingencyConstraint | null }) {
  const n = (id: string) => topo.find((t) => t.node_id === id);
  const fmt = (t?: TopologyNode) => (t && t.capacity !== null && t.capacity !== undefined ? `${fmtNum(t.capacity, 0)} ${t.unit ?? ""}` : "—");
  const flow = (t?: TopologyNode) => (t && t.flow_mw !== null && t.flow_mw !== undefined ? `flow ${fmtNum(t.flow_mw, 0)} MW` : "");
  const hot = (k: ContingencyConstraint) => (constraint === k ? "#dc2626" : "#334155");
  return (
    <svg viewBox="0 0 560 190" className="h-auto w-full max-w-xl" role="img" aria-label="Simulated single-line diagram">
      <g fontSize="11" fill="#334155" fontFamily="ui-sans-serif, system-ui">
        <circle cx="40" cy="95" r="22" fill="#eff6ff" stroke={hot("unit_derate")} strokeWidth="2" />
        <text x="40" y="99" textAnchor="middle" fontWeight="700">G</text>
        <text x="40" y="135" textAnchor="middle">GT unit</text>
        <text x="40" y="149" textAnchor="middle">{fmt(n("gt"))}</text>
        <text x="40" y="163" textAnchor="middle" fill="#64748b">{flow(n("gt"))}</text>
        <line x1="62" y1="95" x2="118" y2="95" stroke="#334155" strokeWidth="2" />
        <circle cx="132" cy="95" r="14" fill="none" stroke={hot("transformer_thermal")} strokeWidth="2" />
        <circle cx="150" cy="95" r="14" fill="none" stroke={hot("transformer_thermal")} strokeWidth="2" />
        <text x="141" y="60" textAnchor="middle">Step-up TX</text>
        <text x="141" y="74" textAnchor="middle">{fmt(n("gsu"))}</text>
        <line x1="164" y1="95" x2="230" y2="95" stroke="#334155" strokeWidth="2" />
        <line x1="230" y1="40" x2="230" y2="150" stroke="#0f172a" strokeWidth="4" />
        <text x="230" y="168" textAnchor="middle">plant bus</text>
        <line x1="230" y1="55" x2="440" y2="55" stroke={hot("line_limit")} strokeWidth="2" />
        <text x="335" y="47" textAnchor="middle">Line A · {fmt(n("line_a"))} · {flow(n("line_a"))}</text>
        <line x1="230" y1="135" x2="440" y2="135" stroke="#334155" strokeWidth="2" />
        <text x="335" y="127" textAnchor="middle">Line B · {fmt(n("line_b"))} · {flow(n("line_b"))}</text>
        <rect x="440" y="35" width="100" height="40" rx="6" fill="#f0fdf4" stroke="#16a34a" />
        <text x="490" y="52" textAnchor="middle" fontWeight="700">SS-A</text>
        <text x="490" y="67" textAnchor="middle">{fmt(n("ss_a"))}</text>
        <rect x="440" y="115" width="100" height="40" rx="6" fill="#f0fdf4" stroke="#16a34a" />
        <text x="490" y="132" textAnchor="middle" fontWeight="700">SS-B</text>
        <text x="490" y="147" textAnchor="middle">{fmt(n("ss_b"))}</text>
        <text x="300" y="185" textAnchor="middle" fill="#64748b">Second unit: {fmt(n("unit2"))} · SIMULATED topology, all capacities are assumptions</text>
      </g>
    </svg>
  );
}

function ContingencyCard({ query }: { query: ReadinessQuery }) {
  const [mode, setMode] = useState<"constraint" | "shortfall">("constraint");
  const [constraint, setConstraint] = useState<ContingencyConstraint>("unit_derate");
  const [shortfall, setShortfall] = useState(15);
  const [severity, setSeverity] = useState(25);
  const [tx, setTx] = useState(200);
  const [ssa, setSsa] = useState(40);
  const [ssb, setSsb] = useState(25);
  const [unit2, setUnit2] = useState(0);
  const [res, setRes] = useState<ContingencyResult | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function evaluate() {
    setBusy(true);
    setErr(null);
    try {
      const r = await getContingency({
        dataset_id: query.dataset_id,
        year: query.year,
        start: query.start ?? 0,
        end: query.end ?? 0,
        shortfall_mw: mode === "shortfall" ? shortfall : null,
        constraint: mode === "constraint" ? constraint : null,
        assumptions: {
          nameplate_mw: query.nameplate_mw,
          power_factor: query.power_factor,
          severity_pct: severity,
          transformer_mva: tx,
          ss_a_spare_mw: ssa,
          ss_b_spare_mw: ssb,
          second_unit_available_mw: unit2,
        },
      });
      setRes(r);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel mb-6">
      <div className="panel-header">
        <div className="panel-title flex items-center gap-2">
          <Network size={18} /> Contingency options (for human evaluation)
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge variant="offline" size="sm" label="SIMULATED TOPOLOGY" />
          <AssumptionBadge />
        </div>
      </div>
      <div className="space-y-4 px-5 py-4">
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900">
          Options for human evaluation. No switching, load transfer or dispatch change is performed by this software.
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-sm text-ink-300">Input</span>
            <select className="input w-44" value={mode} onChange={(e) => setMode(e.target.value as "constraint" | "shortfall")}>
              <option value="constraint">Constraint</option>
              <option value="shortfall">Shortfall (MW)</option>
            </select>
          </label>
          {mode === "constraint" ? (
            <>
              <label className="flex flex-col gap-1">
                <span className="text-sm text-ink-300">Constraint</span>
                <select className="input w-48" value={constraint} onChange={(e) => setConstraint(e.target.value as ContingencyConstraint)}>
                  <option value="unit_derate">Unit derate</option>
                  <option value="transformer_thermal">Transformer thermal</option>
                  <option value="line_limit">Line A limit</option>
                </select>
              </label>
              <NumInput label="Severity %" value={severity} onChange={setSeverity} assumption width="w-24" />
            </>
          ) : (
            <NumInput label="Shortfall MW" value={shortfall} onChange={setShortfall} assumption width="w-24" />
          )}
          <NumInput label="Transformer MVA" value={tx} onChange={setTx} assumption width="w-24" />
          <NumInput label="SS-A spare MW" value={ssa} onChange={setSsa} assumption width="w-24" />
          <NumInput label="SS-B spare MW" value={ssb} onChange={setSsb} assumption width="w-24" />
          <NumInput label="2nd unit MW" value={unit2} onChange={setUnit2} assumption width="w-24" />
          <button type="button" className="btn-primary h-10" onClick={evaluate} disabled={busy}>
            {busy ? <Spinner /> : null} Enumerate options
          </button>
        </div>
        {err ? <ErrorBanner error={err} title="Contingency evaluation failed" /> : null}
        {res ? (
          <>
            <SingleLine topo={res.topology} constraint={res.constraint} />
            <div className="text-base font-semibold text-ink-50">{res.headline}</div>
            <div className="font-mono text-xs text-ink-400">
              {res.output_proxy_computation} · {res.shortfall_computation}
            </div>
            {res.options.length ? (
              <table className="table-base">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Option (evaluate)</th>
                    <th className="text-right">Covered MW</th>
                    <th className="text-right">Residual MW</th>
                    <th>Dependency</th>
                    <th>Prerequisites · notify</th>
                  </tr>
                </thead>
                <tbody>
                  {res.options.map((o) => (
                    <tr key={o.option_id} className={o.applicable ? "" : "opacity-60"}>
                      <td className="font-mono">{o.rank}</td>
                      <td>
                        <div className="font-semibold text-ink-50">{o.title}</div>
                        <div className="text-sm text-ink-300">{o.description}</div>
                        <div className="mt-1 font-mono text-xs text-ink-400">{o.computation}</div>
                      </td>
                      <td className="text-right font-mono">{fmtNum(o.covered_mw, 1)}</td>
                      <td className="text-right font-mono">{fmtNum(o.residual_shortfall_mw, 1)}</td>
                      <td className="text-sm">{humanize(o.external_dependency)}</td>
                      <td className="text-sm text-ink-300">
                        <ul className="list-disc pl-4">
                          {o.prerequisites.map((p, i) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ul>
                        <div className="mt-1 text-xs text-ink-400">Notify: {o.who_to_notify.map(humanize).join(", ")}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <div className="text-xs text-ink-400">{res.shortfall_semantics}</div>
          </>
        ) : null}
      </div>
    </div>
  );
}

const WHY_BULLETS: { text: string; source: string; href: string }[] = [
  {
    text: "“The blackout occurred after an uncontrolled, rapid rise in system voltage and loss of voltage control on a day with multiple concurrent phenomena, accelerated by rapid generation output reductions and disconnections, leading to voltage instability and cascading generation disconnections in Spain.”",
    source: "ENTSO-E Expert Panel, Final Report, 20 March 2026",
    href: "https://www.entsoe.eu/publications/blackout/28-april-2025-iberian-blackout/",
  },
  {
    text: "“…the disconnections of these units without adequate compensation of loss of reactive power by other resources in the system with the capability to inject/absorb reactive power meant that voltages in the system increased…” and “The over-voltage triggered a cascade of generation losses”.",
    source: "ENTSO-E Expert Panel, Factual Report, 3 October 2025",
    href: "https://www.entsoe.eu/publications/blackout/28-april-2025-iberian-blackout/",
  },
  {
    text: "“the system did not have sufficient dynamic voltage control capability” and “The high voltages led to a chain reaction in which the disconnection of each plant led to the disconnection of the next”.",
    source: "Spanish Government committee report, Council of Ministers, 17 June 2025",
    href: "https://www.lamoncloa.gob.es/lang/en/gobierno/councilministers/paginas/2025/20250617-council-press-conference.aspx",
  },
];

export default function GridPage() {
  const [form, setForm] = useState<ReadinessQuery>({
    dataset_id: DATASET_ID,
    year: 2014,
    start: 1200,
    end: 1320,
    nameplate_mw: 160,
    h_constant_s: 5,
    power_factor: 0.85,
  });
  const [query, setQuery] = useState<ReadinessQuery>(form);
  const readiness = useAsync((s) => getReadiness(query, s), [JSON.stringify(query)]);
  const r = readiness.data;

  const [event, setEvent] = useState<GridEvent>("load_step");
  const [useMeta, setUseMeta] = useState(false);
  const [drill, setDrill] = useState<GridDrill | null>(null);
  const [drillErr, setDrillErr] = useState<unknown>(null);
  const [drilling, setDrilling] = useState(false);

  const teyRows = useMemo(() => (r ? toRows(r.charts.tey, "tey", "nameplate", r.charts.nameplate_mw) : []), [r]);
  const titRows = useMemo(() => (r ? toRows(r.charts.tit, "tit", "p99", r.charts.tit_p99_train) : []), [r]);

  async function startDrill() {
    setDrilling(true);
    setDrillErr(null);
    try {
      const d = await runDrill({
        dataset_id: query.dataset_id,
        year: query.year,
        start: query.start ?? 0,
        end: query.end ?? 0,
        event,
        use_meta: useMeta,
        nameplate_mw: query.nameplate_mw,
        h_constant_s: query.h_constant_s,
        power_factor: query.power_factor,
      });
      setDrill(d);
    } catch (e) {
      setDrillErr(e);
    } finally {
      setDrilling(false);
    }
  }

  const set = <K extends keyof ReadinessQuery>(k: K) => (v: ReadinessQuery[K]) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div>
      <PageHeader
        title="Grid support readiness"
        subtitle="What this unit's own historical data says about output headroom and thermal margins, plus labelled assumptions for inertia and reactive capability. Advisory only — not a grid-control system."
        right={
          <>
            <SourceBadge variant="real" />
            <SourceBadge variant="review" label="ADVISORY ONLY" />
          </>
        }
      />

      <details className="panel mb-5 px-5 py-3">
        <summary className="flex cursor-pointer items-center gap-2 font-semibold text-ink-50">
          <BookOpen size={16} /> Why this matters: 28 April 2025
        </summary>
        <ul className="mt-3 space-y-2 text-sm text-ink-200">
          {WHY_BULLETS.map((b) => (
            <li key={b.source}>
              {b.text}{" "}
              <a className="text-blue-700 underline" href={b.href} target="_blank" rel="noreferrer">
                {b.source}
              </a>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-ink-300">
          ThermoMind did not and could not prevent that event, and it is not a grid-control system. Its honest contribution is situational awareness and
          prepared operator procedures. Full sources: <code className="font-mono">docs/GRID_RESILIENCE.md</code>.
        </p>
      </details>

      <div className="panel mb-5 px-5 py-4">
        <div className="flex flex-wrap items-end gap-4">
          <NumInput label="Year" value={form.year} onChange={set("year")} width="w-24" />
          <NumInput label="Start row" value={form.start ?? 0} onChange={set("start")} width="w-24" />
          <NumInput label="End row (excl.)" value={form.end ?? 0} onChange={set("end")} width="w-24" />
          <NumInput label="Nameplate MW" value={form.nameplate_mw} onChange={set("nameplate_mw")} assumption />
          <NumInput label="Inertia H (s)" value={form.h_constant_s} onChange={set("h_constant_s")} step={0.1} assumption />
          <NumInput label="Power factor" value={form.power_factor} onChange={set("power_factor")} step={0.01} assumption />
          <button type="button" className="btn-primary h-10" onClick={() => setQuery(form)}>
            <Gauge size={16} /> Compute readiness
          </button>
        </div>
        {r ? (
          <div className="mt-2 text-xs text-ink-400">
            H typical range {r.assumptions.h_typical_range_s.join("–")} s · {r.assumptions.h_reference}
          </div>
        ) : null}
      </div>

      {readiness.loading ? <PanelSkeleton lines={6} className="mb-5" /> : null}
      {readiness.error ? <ErrorBanner className="mb-5" title="Could not compute readiness" error={readiness.error} onRetry={readiness.reload} /> : null}

      {r ? (
        <>
          <InfoBanner className="mb-4" icon={<Zap size={18} />}>
            <span className="font-semibold">
              <StatusPillSmall s={r.summary.status} /> {r.summary.headline}
            </span>{" "}
            <span className="text-sm text-ink-300">
              {r.window.source_year} samples #{r.window.start}–#{r.window.end - 1} ({r.rows} hourly samples, no timestamps) · training years{" "}
              {r.training_years.join(", ")}
            </span>
          </InfoBanner>
          <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {r.cards.map((c) => (
              <ReadinessCard key={c.key} c={c} />
            ))}
          </div>
          <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <SeriesChart
              title="TEY (output proxy) with nameplate headroom line"
              unit="MWh"
              year={r.year}
              data={teyRows}
              height={220}
              series={[
                { key: "tey", name: "TEY (real)", color: SERIES_COLORS.measured },
                { key: "nameplate", name: `Nameplate ${r.charts.nameplate_mw} (assumption)`, color: "#ca8a04", dashed: true, tag: "ASSUMPTION" },
              ]}
              footer="TEY is MWh per hourly sample as published; not converted to MW."
            />
            <SeriesChart
              title="TIT with training-years p99 (historical envelope)"
              unit="°C"
              year={r.year}
              data={titRows}
              height={220}
              series={[
                { key: "tit", name: "TIT (real)", color: SERIES_COLORS.measured },
                { key: "p99", name: `p99 ${fmtNum(r.charts.tit_p99_train, 1)} °C`, color: SERIES_COLORS.expected, dashed: true, tag: "HISTORICAL, NOT OEM" },
              ]}
            />
          </div>
        </>
      ) : null}

      <div className="panel mb-6">
        <div className="panel-header">
          <div className="panel-title flex items-center gap-2">
            <PlayCircle size={18} /> Run grid-event drill
          </div>
          <SourceBadge variant="synthetic" size="sm" />
        </div>
        <div className="px-5 py-4">
          <div role="alert" className="sticky top-2 z-10 mb-4 flex items-center gap-3 rounded-xl border-2 border-red-400 bg-amber-50 px-4 py-3 font-semibold text-red-800">
            <AlertOctagon size={20} className="shrink-0" /> {drill?.banner ?? BANNER}
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1">
              <span className="text-sm text-ink-300">Event (synthetic)</span>
              <select className="input w-48" value={event} onChange={(e) => setEvent(e.target.value as GridEvent)}>
                <option value="load_step">Load step</option>
                <option value="frequency_dip">Frequency dip</option>
                <option value="overvoltage">Overvoltage</option>
              </select>
            </label>
            <label className="flex h-10 items-center gap-2 text-base text-ink-200">
              <input type="checkbox" checked={useMeta} onChange={(e) => setUseMeta(e.target.checked)} /> Use Meta (Muse Spark)
            </label>
            <button type="button" className="btn-amber h-10" onClick={startDrill} disabled={drilling}>
              {drilling ? <Spinner /> : <PlayCircle size={16} />} Run grid-event drill
            </button>
            {drilling && useMeta ? <span className="text-sm text-ink-400">Muse Spark can take 30–90 s…</span> : null}
          </div>
          {drillErr ? <ErrorBanner className="mt-4" error={drillErr} title="Drill failed" /> : null}
          {drill ? <DrillResult d={drill} /> : null}
        </div>
      </div>

      <ContingencyCard query={query} />
    </div>
  );
}
