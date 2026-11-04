import { ArrowLeftRight, GitCompare } from "lucide-react";
import { useMemo, useState } from "react";
import { listInvestigations, previewScenario } from "../../api/client";
import type { DataQualityReport, Investigation, ScenarioPreviewResponse, SeriesPoint } from "../../api/types";
import { MEASUREMENTS } from "../../api/types";
import { ChartSkeleton, ErrorBanner, InfoBanner, PanelSkeleton, WarnBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SERIES_COLORS, SeriesChart } from "../../components/SeriesChart";
import type { ChartRow } from "../../components/SeriesChart";
import { SourceBadge } from "../../components/SourceBadge";
import { HypothesisStatusPill, InvestigationStatusPill, SeverityPill } from "../../components/StatusPill";
import { useAsync } from "../../hooks/useAsync";
import { fmtNum, fmtSigned, humanize, rangeLabel } from "../../lib/format";
import {
  buildSummary,
  caseOptionLabel,
  dataQualityRows,
  diffEvidence,
  diffHypotheses,
  pickDefaults,
  summarizeToolCalls,
} from "./helpers";
import type { CaseSide, HypothesisCell, ToolCallSummary, ZBand } from "./types";

const PREVIEW_MEASURES = ["AFDP", "TEY", "CDP"];

const SIDE_CLS: Record<CaseSide, string> = {
  A: "bg-blue-600 text-white",
  B: "bg-slate-700 text-white",
};

function SideTag({ side }: { side: CaseSide }) {
  return <span className={`inline-flex h-6 w-6 items-center justify-center rounded-md text-sm font-bold ${SIDE_CLS[side]}`}>{side}</span>;
}

const Dash = () => <span className="text-ink-400">—</span>;

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <div className="mb-2">
        <h2 className="text-lg font-semibold text-ink-50">{title}</h2>
        {hint ? <p className="text-sm text-ink-300">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

// --- case header ------------------------------------------------------------

function CaseBadges({ inv }: { inv: Investigation }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-base font-semibold text-ink-50">{inv.scenario.title}</span>
      {inv.scenario_label === "synthetic_overlay" ? <SourceBadge variant="synthetic" size="sm" /> : <SourceBadge variant="real" size="sm" />}
      {inv.mode === "meta_live" ? (
        <SourceBadge variant="meta" size="sm" label={`META LIVE · ${inv.meta_model ?? "muse-spark-1.3"}`} />
      ) : (
        <SourceBadge variant="offline" size="sm" />
      )}
      <InvestigationStatusPill status={inv.status} />
      {inv.report ? <SeverityPill severity={inv.report.severity} /> : <span className="text-sm text-ink-400">no report</span>}
      <SourceBadge variant="review" size="sm" label="HUMAN REVIEW REQUIRED" />
    </div>
  );
}

function CasePanel({ side, inv, list, value, onChange }: { side: CaseSide; inv: Investigation | null; list: Investigation[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center gap-2">
        <SideTag side={side} />
        <label className="label" htmlFor={`case-${side}`}>
          Case {side}
        </label>
      </div>
      <select id={`case-${side}`} className="input w-full" value={value} onChange={(e) => onChange(e.target.value)}>
        {list.map((i) => (
          <option key={i.case_id} value={i.case_id}>
            {caseOptionLabel(i)}
          </option>
        ))}
      </select>
      {inv ? (
        <div className="mt-3 space-y-2">
          <CaseBadges inv={inv} />
          <div className="font-mono text-sm text-ink-300">{rangeLabel(inv.window)}</div>
          {inv.report ? <div className="text-sm text-ink-200">{inv.report.title}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

// --- preview charts ---------------------------------------------------------

function usePreview(inv: Investigation | null) {
  return useAsync<ScenarioPreviewResponse | null>(
    (signal) => {
      if (!inv) return Promise.resolve(null);
      const r = inv.request;
      return previewScenario(
        {
          dataset_id: r.dataset_id,
          scenario_id: r.scenario_id,
          year: r.year,
          start_index: r.start_index,
          end_index: r.end_index,
          measurements: PREVIEW_MEASURES,
          seed: r.seed,
        },
        signal,
      );
    },
    [inv?.case_id],
  );
}

function toRows(original: SeriesPoint[], overlay: SeriesPoint[]): ChartRow[] {
  const m = new Map<number, ChartRow>();
  for (const p of original) m.set(p.row_index, { row_index: p.row_index, original: p.value, overlay: null });
  for (const p of overlay) {
    const row = m.get(p.row_index) ?? { row_index: p.row_index, original: null, overlay: null };
    row.overlay = p.value;
    m.set(p.row_index, row);
  }
  return Array.from(m.values()).sort((x, y) => x.row_index - y.row_index);
}

function PreviewChart({ side, inv, preview, measure }: { side: CaseSide; inv: Investigation; preview: ScenarioPreviewResponse; measure: string }) {
  const s = preview.series.find((x) => x.measure === measure);
  const info = MEASUREMENTS[measure];
  const synthetic = preview.synthetic;
  const title = (
    <span className="inline-flex items-center gap-2">
      <SideTag side={side} />
      {measure} <span className="font-normal text-ink-300">{info?.name ?? ""}</span>
    </span>
  );
  const series = synthetic
    ? [
        { key: "original", name: "Original (real)", color: SERIES_COLORS.measured },
        { key: "overlay", name: "Synthetic overlay", color: SERIES_COLORS.overlay, dashed: true, tag: undefined },
      ]
    : [{ key: "original", name: "Original (real)", color: SERIES_COLORS.measured }];
  return (
    <SeriesChart
      title={title}
      unit={s?.unit ?? info?.unit ?? ""}
      year={preview.year}
      data={s ? toRows(s.original, synthetic ? s.overlay : []) : []}
      series={series}
      height={200}
      badges={synthetic ? <SourceBadge variant="synthetic" size="sm" /> : <SourceBadge variant="real" size="sm" />}
      footer={`${inv.scenario.scenario_id} · ${rangeLabel({ source_year: preview.year, start: preview.start_index, end: preview.end_index })} · seed ${preview.seed}`}
      emptyMessage={`No ${measure} points returned for this case.`}
    />
  );
}

function PreviewCell({ side, inv, state, measure }: { side: CaseSide; inv: Investigation; state: ReturnType<typeof usePreview>; measure: string }) {
  if (state.loading) return <ChartSkeleton height={200} />;
  if (state.error) return <ErrorBanner title={`Preview for case ${side} failed`} error={state.error} onRetry={state.reload} />;
  if (!state.data) return null;
  return <PreviewChart side={side} inv={inv} preview={state.data} measure={measure} />;
}

// --- hypotheses -------------------------------------------------------------

function HypCell({ c }: { c: HypothesisCell | null }) {
  if (!c) return <span className="text-sm text-ink-400">not in report</span>;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono font-bold text-ink-50">#{c.rank}</span>
      <HypothesisStatusPill status={c.status} />
      <span className="text-xs text-ink-300">
        +{c.supporting} / −{c.contradicting} evidence
      </span>
    </div>
  );
}

function HypothesisTable({ a, b }: { a: Investigation; b: Investigation }) {
  const rows = useMemo(() => diffHypotheses(a, b), [a, b]);
  if (rows.length === 0) return <div className="panel px-5 py-6 text-base text-ink-400">Neither case has report hypotheses to compare.</div>;
  return (
    <div className="panel overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>Hypothesis</th>
            <th>Case A</th>
            <th>Case B</th>
            <th>Differs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={r.differs ? "bg-yellow-50" : ""}>
              <td>
                <div className="font-semibold">{r.name}</div>
                <div className="font-mono text-xs text-ink-400">{humanize(r.key)}</div>
              </td>
              <td>
                <HypCell c={r.a} />
              </td>
              <td>
                <HypCell c={r.b} />
              </td>
              <td>
                {r.differs ? <span className="rounded border border-amber-400 bg-yellow-100 px-1.5 py-0.5 text-xs font-bold text-amber-800">DIFFERS</span> : <span className="text-sm text-ink-400">same</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- evidence ---------------------------------------------------------------

const BAND_CLS: Record<ZBand, string> = {
  none: "text-ink-400",
  small: "text-ink-200",
  moderate: "rounded bg-yellow-100 px-1.5 text-amber-800",
  large: "rounded bg-red-50 px-1.5 text-red-800",
};

function EvidenceDiffView({ a, b }: { a: Investigation; b: Investigation }) {
  const d = useMemo(() => diffEvidence(a, b), [a, b]);
  const triple = (e: typeof a.evidence[number]) => (
    <div className="font-mono text-sm leading-snug">
      <div>obs {fmtNum(e.observed_stat, 3)}</div>
      <div className="text-ink-300">cmp {fmtNum(e.comparison_stat, 3)}</div>
      <div>z {fmtNum(e.z_score, 2)}</div>
      {e.is_synthetic ? <span className="rounded bg-yellow-200 px-1 text-[11px] font-bold text-yellow-900">SYN</span> : null}
    </div>
  );
  const uniqueList = (side: CaseSide, items: typeof d.onlyA) => (
    <div className="panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <SideTag side={side} />
        <span className="label">Only in case {side} ({items.length})</span>
      </div>
      {items.length === 0 ? (
        <span className="text-sm text-ink-400">none</span>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {items.map((e) => (
            <li key={e.evidence_id}>
              <span className="chip border-ink-600 bg-white text-ink-200">{e.evidence_id}</span>{" "}
              <span className="text-ink-100">{e.metric}</span> · z {fmtNum(e.z_score, 2)} · obs {fmtNum(e.observed_stat, 3)} {e.unit}
              {e.is_synthetic ? <span className="ml-1 rounded bg-yellow-200 px-1 text-[11px] font-bold text-yellow-900">SYN</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  return (
    <div className="space-y-4">
      {d.shared.length === 0 ? (
        <div className="panel px-5 py-6 text-base text-ink-400">No evidence id appears in both cases.</div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Evidence id</th>
                <th>Metric</th>
                <th>Case A (obs / comparison / z)</th>
                <th>Case B (obs / comparison / z)</th>
                <th>z difference (B − A)</th>
              </tr>
            </thead>
            <tbody>
              {d.shared.map((r) => (
                <tr key={r.id}>
                  <td className="font-mono text-sm">{r.id}</td>
                  <td>
                    <div className="font-semibold">{r.metric}</div>
                    <div className="text-xs text-ink-400">{r.unit}</div>
                  </td>
                  <td>{triple(r.a)}</td>
                  <td>{triple(r.b)}</td>
                  <td>
                    {r.zDelta === null ? (
                      <Dash />
                    ) : (
                      <span className={`font-mono font-semibold ${BAND_CLS[r.band]}`}>{fmtSigned(r.zDelta, 2)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-ink-700 px-5 py-2 text-xs text-ink-400">
            Colour bands are display aids only: |difference| below 0.5 plain, 0.5 to 2 amber, 2 or more red.
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {uniqueList("A", d.onlyA)}
        {uniqueList("B", d.onlyB)}
      </div>
    </div>
  );
}

// --- data quality -----------------------------------------------------------

function DqList({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-sm text-ink-400">none</span>;
  return (
    <ul className="space-y-1 text-sm">
      {items.map((x, i) => (
        <li key={i}>{x}</li>
      ))}
    </ul>
  );
}

function DataQualityView({ a, b }: { a: DataQualityReport | null; b: DataQualityReport | null }) {
  const rows = useMemo(() => dataQualityRows(a, b), [a, b]);
  return (
    <div className="panel overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>Item</th>
            <th>Case A{a ? "" : " (no data-quality report)"}</th>
            <th>Case B{b ? "" : " (no data-quality report)"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className={r.differs && r.label !== "Notes" ? "bg-yellow-50" : ""}>
              <td className="font-semibold">{r.label}</td>
              <td>
                <DqList items={r.a} />
              </td>
              <td>
                <DqList items={r.b} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- tool calls -------------------------------------------------------------

function ToolCalls({ side, s }: { side: CaseSide; s: ToolCallSummary }) {
  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center gap-2">
        <SideTag side={side} />
        <span className="label">
          {s.total} tool call{s.total === 1 ? "" : "s"}
          {s.failed > 0 ? ` · ${s.failed} failed` : ""}
        </span>
      </div>
      {s.total === 0 ? (
        <span className="text-sm text-ink-400">No tool_call events recorded for this case.</span>
      ) : (
        <>
          <ol className="mb-4 flex flex-wrap gap-1.5">
            {s.sequence.map((c, i) => (
              <li key={`${c.seq}-${i}`} className={`chip ${c.ok ? "border-blue-300 bg-blue-50 text-blue-800" : "border-red-300 bg-red-50 text-red-800"}`}>
                <span className="text-ink-400">{i + 1}.</span> {c.tool}
              </li>
            ))}
          </ol>
          <table className="table-base">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Calls</th>
                <th>Failed</th>
              </tr>
            </thead>
            <tbody>
              {s.counts.map((c) => (
                <tr key={c.tool}>
                  <td className="font-mono text-sm">{c.tool}</td>
                  <td className="font-mono">{c.count}</td>
                  <td className="font-mono">{c.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// --- page -------------------------------------------------------------------

export default function ComparePage() {
  const inv = useAsync((s) => listInvestigations(s), []);
  const list = useMemo(() => inv.data ?? [], [inv.data]);
  const defaults = useMemo(() => pickDefaults(list), [list]);
  const [pickA, setPickA] = useState<string | null>(null);
  const [pickB, setPickB] = useState<string | null>(null);

  const byId = useMemo(() => new Map(list.map((i) => [i.case_id, i] as const)), [list]);
  const idA = pickA && byId.has(pickA) ? pickA : defaults.a;
  const idB = pickB && byId.has(pickB) ? pickB : defaults.b;
  const caseA = idA ? (byId.get(idA) ?? null) : null;
  const caseB = idB ? (byId.get(idB) ?? null) : null;

  const prevA = usePreview(caseA);
  const prevB = usePreview(caseB);

  const ready = caseA !== null && caseB !== null;
  const same = ready && caseA.case_id === caseB.case_id;
  const summary = useMemo(() => (ready ? buildSummary(caseA, caseB) : []), [ready, caseA, caseB]);
  const toolsA = useMemo(() => (caseA ? summarizeToolCalls(caseA) : null), [caseA]);
  const toolsB = useMemo(() => (caseB ? summarizeToolCalls(caseB) : null), [caseB]);

  const swap = () => {
    setPickA(idB);
    setPickB(idA);
  };

  return (
    <div>
      <PageHeader
        title="Compare cases"
        subtitle="Side-by-side view of two stored investigations. Every case is a draft that requires human review; this page only describes how the stored outputs differ and says nothing about correctness."
        right={
          <button type="button" className="btn-secondary" onClick={swap} disabled={!ready}>
            <ArrowLeftRight size={16} /> Swap A and B
          </button>
        }
      />

      {inv.error ? <ErrorBanner title="Could not load investigations" error={inv.error} onRetry={inv.reload} /> : null}
      {inv.loading ? <PanelSkeleton lines={5} /> : null}

      {!inv.loading && !inv.error && list.length < 2 ? (
        <div className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
          <GitCompare size={30} className="text-ink-400" />
          <div className="text-lg font-semibold">{list.length === 0 ? "No investigations yet" : "Only one investigation stored"}</div>
          <p className="max-w-md text-base text-ink-300">Run at least two investigations (for example S02 and S03) from the Overview page, then return here to compare them.</p>
        </div>
      ) : null}

      {list.length >= 2 ? (
        <>
          <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <CasePanel side="A" inv={caseA} list={list} value={idA ?? ""} onChange={setPickA} />
            <CasePanel side="B" inv={caseB} list={list} value={idB ?? ""} onChange={setPickB} />
          </div>

          {same ? <WarnBanner className="mb-6">Case A and case B are the same investigation. Choose two different cases to see differences.</WarnBanner> : null}

          {ready ? (
            <>
              <Section title="Summary of differences" hint="Generated from stored values only; no interpretation beyond what the two cases contain.">
                <div className="panel p-5">
                  <ul className="list-disc space-y-1.5 pl-5 text-base text-ink-100">
                    {summary.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                  {caseA.scenario_label === "synthetic_overlay" || caseB.scenario_label === "synthetic_overlay" ? (
                    <InfoBanner className="mt-4">
                      At least one case uses a synthetic overlay on real public data (UCI, no timestamps). Differences between cases reflect the scenario transformations and the stored outputs, not observed plant faults.
                    </InfoBanner>
                  ) : null}
                </div>
              </Section>

              <Section title="Scenario previews" hint="AFDP, TEY and CDP over each case's window. Blue is the original real data; the dashed line is the synthetic overlay when present.">
                <div className="space-y-4">
                  {PREVIEW_MEASURES.map((m) => (
                    <div key={m} className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                      <PreviewCell side="A" inv={caseA} state={prevA} measure={m} />
                      <PreviewCell side="B" inv={caseB} state={prevB} measure={m} />
                    </div>
                  ))}
                </div>
              </Section>

              <Section title="Hypothesis comparison" hint="Rank and status as reported in each case. Highlighted rows differ.">
                <HypothesisTable a={caseA} b={caseB} />
              </Section>

              <Section title="Evidence comparison" hint="Evidence ids present in both cases with observed value, comparison value and z-score side by side.">
                <EvidenceDiffView a={caseA} b={caseB} />
              </Section>

              <Section title="Data quality" hint="Highlighted rows hold different entries in the two cases.">
                <DataQualityView a={caseA.data_quality} b={caseB.data_quality} />
              </Section>

              <Section title="Agent tool-call sequence" hint="Tool calls recorded in each case's event log, in order.">
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {toolsA ? <ToolCalls side="A" s={toolsA} /> : null}
                  {toolsB ? <ToolCalls side="B" s={toolsB} /> : null}
                </div>
              </Section>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
