import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  ClipboardCheck,
  Gauge,
  Info,
  Leaf,
  ShieldCheck,
  Sparkles,
  Users,
  Zap,
  Activity,
} from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ErrorBanner, InfoBanner, PanelSkeleton, Spinner, WarnBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtDateTime } from "../../lib/format";
import { createExecutiveBrief, getExecutiveOverview, listExecutiveBriefs } from "./api";
import type { AttentionItem, ExecutiveBrief, Kpi, KpiGroup, Provenance } from "./types";

const YEARS = [2011, 2012, 2013, 2014, 2015];

const GROUPS: { id: KpiGroup; title: string; icon: ReactNode; question: string }[] = [
  { id: "performance", title: "Performance", icon: <Gauge size={18} />, question: "Are we producing what the machine should, for the fuel we burn?" },
  { id: "reliability", title: "Reliability", icon: <Activity size={18} />, question: "Where could a forced outage start?" },
  { id: "compliance", title: "Compliance", icon: <Leaf size={18} />, question: "How exposed are we on emissions?" },
  { id: "grid", title: "Grid", icon: <Zap size={18} />, question: "What could we offer the grid operator?" },
  { id: "people_knowledge", title: "People & knowledge", icon: <Users size={18} />, question: "Is what our people know being written down?" },
  { id: "decisions", title: "Decisions", icon: <ClipboardCheck size={18} />, question: "What is waiting on a person, and how fast do we decide?" },
  { id: "safety", title: "Safety & OT security", icon: <ShieldCheck size={18} />, question: "Can this tool touch the plant? (It cannot.)" },
];

const PROV: Record<Provenance, { label: string; cls: string }> = {
  real: { label: "REAL PUBLIC DATA", cls: "border-green-300 bg-green-50 text-green-800" },
  model_derived: { label: "MODEL-DERIVED", cls: "border-dashed border-green-400 bg-white text-green-800" },
  simulated: { label: "SIMULATED", cls: "border-yellow-400 bg-yellow-100 text-yellow-900" },
  assumption: { label: "ASSUMPTION", cls: "border-orange-300 bg-orange-50 text-orange-900" },
  prototype_metric: { label: "PROTOTYPE METRIC", cls: "border-blue-300 bg-blue-50 text-blue-800" },
};

function ProvenanceBadge({ p }: { p: Provenance }) {
  const s = PROV[p];
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide ${s.cls}`}>
      {s.label}
    </span>
  );
}

function fmtValue(k: Kpi): string {
  if (!k.available || k.value === null || k.value === undefined) return "—";
  if (typeof k.value === "number") return k.value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return k.value;
}

function KpiTile({ k }: { k: Kpi }) {
  const [open, setOpen] = useState(false);
  const long = typeof k.value === "string" && k.value.length > 14;
  return (
    <div className={`panel flex flex-col gap-2 px-5 py-4 ${k.available ? "" : "opacity-75"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-base font-semibold text-ink-100">{k.label}</div>
        <button
          type="button"
          className="shrink-0 rounded-md p-1 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
          aria-expanded={open}
          aria-label={`What this figure is and is not: ${k.label}`}
          title={k.caveat}
          onClick={() => setOpen((v) => !v)}
        >
          <Info size={18} />
        </button>
      </div>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={`font-mono font-semibold tabular-nums text-ink-50 ${long ? "text-xl" : "text-3xl"}`}>{fmtValue(k)}</span>
        {k.unit && k.available ? <span className="text-base text-ink-300">{k.unit}</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ProvenanceBadge p={k.provenance} />
        {!k.available ? <span className="text-xs font-semibold uppercase text-ink-400">unavailable</span> : null}
      </div>
      {open ? (
        <div className="rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-sm text-ink-200">
          <p>{k.caveat}</p>
          <p className="mt-1 font-mono text-xs text-ink-400">source: {k.source_endpoint}</p>
        </div>
      ) : null}
    </div>
  );
}

function AttentionCard({ a }: { a: AttentionItem }) {
  const strong = a.severity === "attention";
  return (
    <div
      className={`flex flex-col gap-2 rounded-xl border px-4 py-3 ${
        strong ? "border-amber-300 bg-amber-50 text-amber-950" : "border-ink-700 bg-white text-ink-100"
      }`}
    >
      <div className="flex items-start gap-2">
        {strong ? <AlertTriangle size={20} className="mt-0.5 shrink-0 text-amber-700" /> : <Info size={20} className="mt-0.5 shrink-0 text-ink-400" />}
        <div className="text-base font-semibold">{a.title}</div>
      </div>
      <p className="text-sm">{a.detail}</p>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
        <span className="rounded-md border border-ink-600 bg-white px-2 py-0.5 text-sm font-medium text-ink-100">
          Owner: {a.persona_name}
        </span>
        <Link to={a.link} className="inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline">
          Open <ArrowRight size={14} />
        </Link>
      </div>
      <div className="text-xs text-ink-400" title="Deterministic rule that raised this item">rule: {a.rule}</div>
    </div>
  );
}

function List({ title, items }: { title: string; items: ReactNode[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="label mb-1.5">{title}</div>
      <ul className="list-disc space-y-1 pl-5 text-base text-ink-100">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

function BriefView({ b }: { b: ExecutiveBrief }) {
  const d = b.brief;
  return (
    <div className="panel p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SourceBadge variant="review" label="DRAFT — EXECUTIVE BRIEF, HUMAN REVIEW REQUIRED" />
        {b.meta_used ? <SourceBadge variant="meta" label={`META LIVE · ${b.meta_model ?? ""}`} /> : <SourceBadge variant="offline" label="OFFLINE FALLBACK" />}
        <span className="text-sm text-ink-400">
          {fmtDateTime(b.created_at_utc)} · {b.brief_id}
          {b.rewrite_used ? " · one validator rewrite" : ""}
        </span>
      </div>
      <h2 className="text-xl font-bold text-ink-50">{d.headline}</h2>
      <p className="mt-2 text-base text-ink-200">{d.situation}</p>
      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <List title="Risks" items={d.risks} />
        <List
          title="Decisions needed"
          items={d.decisions_needed.map((x, i) => (
            <span key={i}>
              <strong>{x.decision}</strong>
              {x.owner_persona ? <span className="text-ink-300"> — owner: {x.owner_persona.replace(/_/g, " ")}</span> : null}
              {x.why ? <span className="block text-sm text-ink-300">{x.why}</span> : null}
            </span>
          ))}
        />
        <List title="Money and time: what is not known" items={d.money_and_time_caveats} />
        <List title="Next 30 days" items={d.next_30_days} />
      </div>
      <p className="mt-4 text-sm text-ink-300">{b.source_label}</p>
      {b.fallback_reason ? <p className="text-sm text-ink-400">Fallback reason: {b.fallback_reason}</p> : null}
      <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-950">{b.disclaimer}</p>
    </div>
  );
}

export default function ExecutivePage() {
  const [year, setYear] = useState(2014);
  const ov = useAsync((s) => getExecutiveOverview(year, s), [year]);
  const briefs = useAsync((s) => listExecutiveBriefs(1, s), []);
  const [brief, setBrief] = useState<ExecutiveBrief | null>(null);
  const [busy, setBusy] = useState(false);
  const [briefErr, setBriefErr] = useState<unknown>(null);
  const shown = brief ?? briefs.data?.[0] ?? null;

  async function generate() {
    setBusy(true);
    setBriefErr(null);
    try {
      setBrief(await createExecutiveBrief(year));
    } catch (e) {
      setBriefErr(e);
    } finally {
      setBusy(false);
    }
  }

  const data = ov.data;
  const attention = data?.attention ?? [];
  return (
    <div className="text-[17px]">
      <PageHeader
        title="Executive view"
        subtitle="What a power-company CEO would ask of this plant: output vs expected, forced-outage signals, compliance exposure, grid headroom, open decisions and knowledge capture. Every figure shows where it comes from and what it is not."
        right={
          <label className="flex items-center gap-2 text-base text-ink-200">
            Source year
            <select className="input h-10 w-28" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Source year">
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {ov.error ? <ErrorBanner error={ov.error} title="Could not load the executive overview" onRetry={ov.reload} className="mb-5" /> : null}

      <section aria-labelledby="attn" className="mb-7">
        <h2 id="attn" className="mb-3 flex items-center gap-2 text-lg font-bold text-ink-50">
          <Briefcase size={20} /> Needs attention
        </h2>
        {ov.loading ? (
          <PanelSkeleton lines={2} />
        ) : attention.length ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {attention.map((a) => (
              <AttentionCard key={a.id} a={a} />
            ))}
          </div>
        ) : data ? (
          <InfoBanner>No rule fired for {data.year}. That is not proof of no risk: the data has no fault labels.</InfoBanner>
        ) : null}
      </section>

      {data?.sources_unavailable.length ? (
        <WarnBanner className="mb-5">Some sources were unavailable: {data.sources_unavailable.join("; ")}</WarnBanner>
      ) : null}

      {ov.loading ? (
        <PanelSkeleton lines={6} />
      ) : data ? (
        GROUPS.map((g) => {
          const ks = data.kpis.filter((k) => k.group === g.id);
          if (!ks.length) return null;
          return (
            <section key={g.id} className="mb-7" aria-labelledby={`g-${g.id}`}>
              <div className="mb-3">
                <h2 id={`g-${g.id}`} className="flex items-center gap-2 text-lg font-bold text-ink-50">
                  {g.icon} {g.title}
                </h2>
                <p className="text-sm text-ink-300">{g.question}</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {ks.map((k) => (
                  <KpiTile key={k.key} k={k} />
                ))}
              </div>
            </section>
          );
        })
      ) : null}

      <section aria-labelledby="brief" className="mb-7">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="brief" className="flex items-center gap-2 text-lg font-bold text-ink-50">
            <Sparkles size={20} /> Executive brief
          </h2>
          <button type="button" className="btn-primary h-11 px-5 text-base" onClick={generate} disabled={busy || !data}>
            {busy ? <Spinner /> : <Sparkles size={18} />} {busy ? "Drafting (Muse Spark, up to a few minutes)…" : "Generate executive brief"}
          </button>
        </div>
        <p className="mb-3 text-sm text-ink-300">
          One Meta Muse Spark call over the overview above. A validator rejects control language, dates, money claims, unknown case
          ids and any number that is not in the overview; one rewrite, else a labelled deterministic fallback.
        </p>
        {briefErr ? <ErrorBanner error={briefErr} title="Brief generation failed" className="mb-3" /> : null}
        {shown ? <BriefView b={shown} /> : <InfoBanner>No brief drafted yet.</InfoBanner>}
      </section>

      <footer className="mt-8 border-t border-ink-700 pt-4 text-base font-medium text-ink-200">
        {data?.footer ?? "All figures are prototype metrics from public data and simulated subsystems; no financial outcomes are claimed."}
      </footer>
    </div>
  );
}
