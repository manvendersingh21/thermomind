import { ArrowLeft, ClipboardList, Download, FlaskConical, Info, ListChecks, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { exportUrl, getInvestigation, getSeries, previewScenario } from "../api/client";
import { MEASUREMENTS } from "../api/types";
import type { Evidence, Investigation, ScenarioPreviewResponse, SeriesResponse } from "../api/types";
import { AgentTimeline } from "../components/AgentTimeline";
import { EvidenceChips } from "../components/EvidenceChip";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { ChartSkeleton, ErrorBanner, InfoBanner, PanelSkeleton, WarnBanner } from "../components/Feedback";
import { HypothesisCard } from "../components/HypothesisCard";
import { PageHeader } from "../components/Layout";
import { SERIES_COLORS, SeriesChart } from "../components/SeriesChart";
import type { ChartRow, ChartSeries } from "../components/SeriesChart";
import { PlantSchematic } from "../components/PlantSchematic";
import { ReviewPanel } from "../components/ReviewPanel";
import { WhereToLook } from "../components/WhereToLook";
import { SourceBadge } from "../components/SourceBadge";
import { InvestigationStatusPill, SeverityPill } from "../components/StatusPill";
import { useAsync } from "../hooks/useAsync";
import { PrecedentsPanel, WhatIfConsole, WorkRequestBanner } from "../plant";
import { CaseActivityFeed } from "../features/collab/CaseActivityFeed";
import { DominoMap } from "../features/collab/DominoMap";
import { fmtDateTime, fmtInt, fmtNum, fmtSigned, humanize, rangeLabel } from "../lib/format";

const PREVIEW_MEASURES = ["AFDP", "TEY", "CDP"];

interface PreviewBundle {
  preview: ScenarioPreviewResponse;
  context: Record<string, SeriesResponse | null>;
}

function buildRows(measure: string, bundle: PreviewBundle, synthetic: boolean): ChartRow[] {
  const byIndex = new Map<number, ChartRow>();
  const ctx = bundle.context[measure];
  if (ctx) {
    for (const p of ctx.points) {
      const row: ChartRow = { row_index: p.row_index, original: p.value };
      if (measure === "TEY") row.expected = p.expected;
      byIndex.set(p.row_index, row);
    }
  }
  const s = bundle.preview.series.find((x) => x.measure === measure);
  if (s) {
    s.original.forEach((p, i) => {
      const row = byIndex.get(p.row_index) ?? { row_index: p.row_index };
      row.original = p.value;
      if (synthetic) row.overlay = s.overlay[i]?.value ?? null;
      if (measure === "TEY" && s.expected) row.expected = s.expected[i]?.value ?? row.expected ?? null;
      byIndex.set(p.row_index, row);
    });
  }
  return [...byIndex.values()].sort((a, b) => a.row_index - b.row_index);
}

function Section({ title, icon, children, className = "" }: { title: string; icon?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div className="panel-title flex items-center gap-2">
          {icon}
          {title}
        </div>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

function BulletList({ items, empty = "none" }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <div className="text-base text-ink-400">{empty}</div>;
  return (
    <ul className="list-disc space-y-1.5 pl-5 text-base text-ink-100">
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

export function InvestigationPage() {
  const { caseId = "" } = useParams();
  const invState = useAsync((s) => getInvestigation(caseId, s), [caseId]);
  const [inv, setInv] = useState<Investigation | null>(null);
  useEffect(() => setInv(invState.data), [invState.data]);

  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const evidenceById = useMemo(() => new Map<string, Evidence>((inv?.evidence ?? []).map((e) => [e.evidence_id, e])), [inv]);
  const onOpen = useCallback((id: string) => setOpenEvidence(id), []);
  const onClose = useCallback(() => setOpenEvidence(null), []);

  const previewState = useAsync(
    async (signal): Promise<PreviewBundle | null> => {
      if (!inv) return null;
      const r = inv.request;
      const preview = await previewScenario(
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
      // real context (reference + window) for each measure; tolerant to failure
      const ctxResults = await Promise.allSettled(
        PREVIEW_MEASURES.map((m) =>
          getSeries(
            r.dataset_id,
            { measure: m, year: inv.reference.source_year, start: inv.reference.start, limit: inv.window.end - inv.reference.start, include_expected: m === "TEY" },
            signal,
          ),
        ),
      );
      const context: Record<string, SeriesResponse | null> = {};
      ctxResults.forEach((res, i) => (context[PREVIEW_MEASURES[i]] = res.status === "fulfilled" ? res.value : null));
      return { preview, context };
    },
    [inv?.case_id],
  );

  if (invState.loading && !inv) {
    return (
      <div className="space-y-4">
        <PanelSkeleton lines={2} />
        <div className="grid grid-cols-3 gap-4">
          <ChartSkeleton height={200} />
          <ChartSkeleton height={200} />
          <ChartSkeleton height={200} />
        </div>
        <PanelSkeleton lines={6} />
      </div>
    );
  }
  if (invState.error || !inv) {
    return (
      <div>
        <Link to="/investigations" className="mb-4 inline-flex items-center gap-1 text-base text-ink-300 hover:text-blue-700">
          <ArrowLeft size={16} /> All investigations
        </Link>
        <ErrorBanner title={`Could not load case ${caseId}`} error={invState.error ?? new Error("Not found")} onRetry={invState.reload} />
      </div>
    );
  }

  const report = inv.report;
  const synthetic = inv.scenario_label === "synthetic_overlay";
  const hypotheses = report ? [...report.hypotheses].sort((a, b) => a.rank - b.rank) : [];
  const noNotableAnomaly =
    !!report && report.severity === "informational" && (hypotheses.length === 0 || hypotheses.every((h) => h.status !== "possible" || h.key === "unknown"));
  const insufficientEvidence = inv.evidence.length === 0 || (!!report && hypotheses.length > 0 && hypotheses.every((h) => h.status === "inconclusive"));
  const missingEvidence = openEvidence !== null && !evidenceById.has(openEvidence) ? openEvidence : null;
  const windowHighlight = { start: inv.window.start, end: inv.window.end, label: "case window" };

  const seriesFor = (measure: string): ChartSeries[] => {
    const out: ChartSeries[] = [{ key: "original", name: `Original ${measure} (real)`, color: SERIES_COLORS.measured }];
    if (synthetic && inv.scenario.affected_measurements.includes(measure)) {
      out.push({ key: "overlay", name: "Synthetic overlay", color: SERIES_COLORS.overlay });
    }
    if (measure === "TEY") out.push({ key: "expected", name: "Model expected", color: SERIES_COLORS.expected, dashed: true, tag: "MODEL-DERIVED" });
    return out;
  };

  return (
    <div>
      <Link to="/investigations" className="mb-3 inline-flex items-center gap-1 text-base text-ink-300 hover:text-blue-700">
        <ArrowLeft size={16} /> All investigations
      </Link>
      <PageHeader
        title={report?.title ?? `${inv.scenario.title} — ${inv.case_id}`}
        subtitle={
          <span className="font-mono text-sm text-ink-300">
            {inv.case_id} · window {rangeLabel(inv.window)} · reference {rangeLabel(inv.reference)} · created {fmtDateTime(inv.created_at_utc)}
            {inv.completed_at_utc ? ` · completed ${fmtDateTime(inv.completed_at_utc)}` : ""}
          </span>
        }
        right={
          <a href={exportUrl(inv.case_id)} download={`${inv.case_id}.json`} className="btn-secondary">
            <Download size={16} /> Download JSON
          </a>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <SourceBadge variant="real" />
        {synthetic ? <SourceBadge variant="synthetic" /> : null}
        {inv.model_version ? <SourceBadge variant="model" label={`MODEL-DERIVED · ${inv.model_version}`} /> : <SourceBadge variant="model" label="MODEL-DERIVED · no model" />}
        {inv.mode === "meta_live" ? (
          <SourceBadge variant="meta" label={`META LIVE · ${inv.meta_model ?? "muse-spark-1.3"}`} />
        ) : (
          <SourceBadge variant="offline" label="OFFLINE PREVIEW — not a Meta inference" />
        )}
        <SourceBadge variant="review" />
        <InvestigationStatusPill status={inv.status} />
        {report ? <SeverityPill severity={report.severity} /> : null}
      </div>

      <div className="mb-5">
        <WorkRequestBanner caseId={inv.case_id} />
      </div>

      {inv.status === "failed" ? (
        <ErrorBanner className="mb-5" title="Investigation failed" error={new Error(inv.error ?? "Unknown error")} />
      ) : null}
      {inv.status === "needs_review" && !report ? (
        <WarnBanner className="mb-5">
          The model did not produce a report that passed validation. The deterministic summary below is shown instead; it is tool output,
          not a diagnosis.
        </WarnBanner>
      ) : null}
      {report && inv.mode === "offline_preview" ? (
        <InfoBanner className="mb-5" icon={<Info size={18} />}>
          This report was assembled offline from deterministic tool outputs (no Meta inference). It is a structural preview of what the agent
          would receive and is labelled accordingly.
        </InfoBanner>
      ) : null}
      {noNotableAnomaly ? (
        <InfoBanner className="mb-5" icon={<Info size={18} />}>
          <strong className="text-green-800">No notable anomaly</strong> was identified for this window: the report is informational and no
          hypothesis reaches “possible”.
        </InfoBanner>
      ) : null}
      {insufficientEvidence ? (
        <WarnBanner className="mb-5">
          <strong>Insufficient evidence.</strong> {inv.evidence.length === 0 ? "No evidence was produced by the deterministic tools for this case." : "Every hypothesis is inconclusive."}{" "}
          Review the additional-data requests before drawing conclusions.
        </WarnBanner>
      ) : null}

      {report ? (
        <div className="panel mb-5 px-5 py-4">
          <div className="label mb-1.5">Summary</div>
          <p className="text-lg leading-relaxed text-ink-50">{report.summary}</p>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-400">
            <span>
              data source <span className="font-mono text-ink-200">{report.data_source}</span>
            </span>
            <span>
              scenario label <span className="font-mono text-ink-200">{report.scenario_label}</span>
            </span>
            <span>
              report status <span className="font-mono text-amber-800">{report.report_status}</span>
            </span>
            {inv.report_hash ? (
              <span>
                hash <span className="font-mono text-ink-200">{inv.report_hash.slice(0, 16)}…</span>
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* scenario preview charts */}
      <div className="mb-5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-ink-50">Scenario preview — original (real) vs overlay, case window highlighted</h2>
          <div className="text-sm text-ink-300">
            Context shows the 240 real reference samples before the window. {synthetic ? "Overlay applies only inside the window." : "No overlay for a real-only case."}
          </div>
        </div>
        {previewState.error ? <ErrorBanner title="Could not load scenario preview" error={previewState.error} onRetry={previewState.reload} /> : null}
        <div className="grid grid-cols-3 gap-4">
          {previewState.loading || !previewState.data
            ? PREVIEW_MEASURES.map((m) => (previewState.error ? null : <ChartSkeleton key={m} height={200} />))
            : PREVIEW_MEASURES.map((m) => {
                const s = previewState.data!.preview.series.find((x) => x.measure === m);
                return (
                  <SeriesChart
                    key={m}
                    height={200}
                    title={
                      <span>
                        {m} <span className="text-ink-400">({s?.unit ?? MEASUREMENTS[m].unit})</span>
                      </span>
                    }
                    unit={s?.unit ?? MEASUREMENTS[m].unit}
                    year={inv.window.source_year}
                    data={buildRows(m, previewState.data!, synthetic)}
                    series={seriesFor(m)}
                    highlight={windowHighlight}
                    badges={synthetic && inv.scenario.affected_measurements.includes(m) ? <SourceBadge variant="synthetic" size="sm" /> : <SourceBadge variant="real" size="sm" />}
                  />
                );
              })}
        </div>
        {synthetic && previewState.data ? (
          <div className="panel mt-4 px-5 py-4">
            <div className="mb-2 flex items-center gap-2">
              <FlaskConical size={16} className="text-amber-700" />
              <span className="text-base font-semibold text-amber-800">Synthetic transformations applied to a copy of the window rows</span>
              <span className="font-mono text-sm text-ink-400">seed {previewState.data.preview.seed}</span>
            </div>
            <table className="table-base">
              <thead>
                <tr>
                  <th>Measurement</th>
                  <th>Operation</th>
                  <th>Parameters</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {previewState.data.preview.transformations.map((t, i) => (
                  <tr key={i}>
                    <td className="font-mono text-amber-800">{t.measurement}</td>
                    <td className="font-mono">{t.operation}</td>
                    <td className="font-mono text-sm text-ink-300">{JSON.stringify(t.params)}</td>
                    <td>{t.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {!report ? (
        <div className="mb-5 grid grid-cols-2 gap-4">
          <Section title="Validation errors" icon={<ShieldAlert size={18} className="text-amber-700" />}>
            <BulletList items={inv.validation_errors} empty="No validation errors recorded." />
          </Section>
          <Section title="Deterministic summary (tool outputs — not a diagnosis)" icon={<ClipboardList size={18} className="text-blue-700" />}>
            <pre className="max-h-96 overflow-auto rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm text-ink-100">
              {JSON.stringify(inv.deterministic_summary, null, 2)}
            </pre>
          </Section>
        </div>
      ) : null}

      {report ? (
        <>
          <Section title="Observations" icon={<ClipboardList size={18} className="text-blue-700" />} className="mb-5">
            {report.observations.length === 0 ? (
              <div className="text-base text-ink-400">No observations recorded.</div>
            ) : (
              <ol className="space-y-3">
                {report.observations.map((o, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="mt-0.5 font-mono text-sm text-ink-400">{i + 1}.</span>
                    <div>
                      <div className="text-base text-ink-50">{o.statement}</div>
                      <div className="mt-1">
                        <EvidenceChips ids={o.evidence_ids} evidenceById={evidenceById} onOpen={onOpen} />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Section>

          <h2 className="mb-2 text-lg font-semibold text-ink-50">Hypotheses (ranked)</h2>
          <div className="mb-5 space-y-4">
            {hypotheses.length === 0 ? <div className="panel px-5 py-4 text-base text-ink-400">No hypotheses in this report.</div> : null}
            {hypotheses.map((h) => (
              <HypothesisCard key={`${h.rank}-${h.name}`} hypothesis={h} evidenceById={evidenceById} onOpenEvidence={onOpen} />
            ))}
          </div>

          <div className="mb-5">
            <WhereToLook
              report={report}
              scenarioSynthetic={synthetic}
              renderSchematic={(parts) => (
                <PlantSchematic bare lookHere={parts} highlight={synthetic ? inv.scenario.affected_measurements : []} />
              )}
            />
          </div>

          <div className="mb-5 grid grid-cols-3 gap-4">
            <Section title="Additional data needed" icon={<ListChecks size={18} className="text-amber-700" />}>
              <BulletList items={report.additional_data_needed} />
            </Section>
            <Section title="Engineer review checks" icon={<ListChecks size={18} className="text-blue-700" />}>
              <BulletList items={report.engineer_review_checks} />
            </Section>
            <Section title="Limitations" icon={<Info size={18} className="text-ink-300" />}>
              <BulletList items={report.limitations} />
            </Section>
          </div>
          <WarnBanner className="mb-5" icon={<ShieldAlert size={20} />}>
            <strong>Disclaimer:</strong> {report.disclaimer} Status: {humanize(report.report_status)}. No plant control actions are possible from
            this software.
          </WarnBanner>
        </>
      ) : null}

      {/* data quality + baseline */}
      <div className="mb-5 grid grid-cols-2 gap-4">
        <Section title="Data quality" icon={<ShieldAlert size={18} className="text-ink-300" />}>
          {inv.data_quality ? (
            <div className="space-y-3 text-base">
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-300">
                <span>
                  source <span className="font-mono text-ink-100">{inv.data_quality.source}</span>
                </span>
                <span>
                  label <span className="font-mono text-ink-100">{inv.data_quality.scenario_label}</span>
                </span>
                <span>
                  synthetic measurements{" "}
                  <span className="font-mono text-amber-800">{inv.data_quality.synthetic_measurements.length ? inv.data_quality.synthetic_measurements.join(", ") : "none"}</span>
                </span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="label mb-1">Missing values</div>
                  <div className="font-mono text-sm text-ink-100">
                    {Object.entries(inv.data_quality.missing_values).filter(([, v]) => v > 0).length === 0
                      ? "none"
                      : Object.entries(inv.data_quality.missing_values)
                          .filter(([, v]) => v > 0)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")}
                  </div>
                </div>
                <div>
                  <div className="label mb-1">Rows outside training range</div>
                  <div className="font-mono text-sm text-ink-100">
                    {Object.entries(inv.data_quality.out_of_training_range).filter(([, v]) => v > 0).length === 0
                      ? "none"
                      : Object.entries(inv.data_quality.out_of_training_range)
                          .filter(([, v]) => v > 0)
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(" · ")}
                  </div>
                </div>
              </div>
              {inv.data_quality.sensor_consistency_flags.length > 0 ? (
                <div>
                  <div className="label mb-1">Sensor consistency flags</div>
                  <ul className="list-disc pl-5 text-red-800">
                    {inv.data_quality.sensor_consistency_flags.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {inv.data_quality.notes.length > 0 ? <BulletList items={inv.data_quality.notes} /> : null}
            </div>
          ) : (
            <div className="text-base text-ink-400">No data-quality report.</div>
          )}
        </Section>
        <Section title="Baseline comparison (model-derived)" icon={<Info size={18} className="text-green-800" />}>
          {inv.baseline ? (
            <div className="text-base">
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["Observed TEY mean", `${fmtNum(inv.baseline.observed_tey_mean, 2)} ${inv.baseline.unit}`],
                  ["Expected TEY mean", `${fmtNum(inv.baseline.expected_tey_mean, 2)} ${inv.baseline.unit}`],
                  ["Residual mean", `${fmtSigned(inv.baseline.residual_mean, 2)} ${inv.baseline.unit}`],
                  ["Residual z", fmtNum(inv.baseline.residual_z, 2)],
                  ["Reference residual mean", `${fmtSigned(inv.baseline.reference_residual_mean, 2)} ${inv.baseline.unit}`],
                  ["Holdout MAE / R²", `${fmtNum(inv.baseline.holdout_mae, 2)} / ${fmtNum(inv.baseline.holdout_r2, 3)}`],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2">
                    <div className="text-sm text-ink-300">{k}</div>
                    <div className="font-mono text-lg text-ink-50">{v}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-sm text-ink-400">
                model <span className="font-mono text-ink-200">{inv.baseline.model_version}</span> · residual std window {fmtNum(inv.baseline.residual_std_window, 2)} · validation{" "}
                {fmtNum(inv.baseline.residual_std_validation, 2)}
              </div>
              {inv.baseline.caveats.length > 0 ? (
                <div className="mt-3">
                  <BulletList items={inv.baseline.caveats} />
                </div>
              ) : null}
            </div>
          ) : (
            <div className="text-base text-ink-400">No baseline comparison (model not available for this case).</div>
          )}
        </Section>
      </div>

      {/* evidence ledger */}
      <div className="panel mb-5 overflow-hidden">
        <div className="panel-header">
          <div>
            <div className="panel-title">Evidence ledger</div>
            <div className="mt-0.5 text-sm text-ink-300">{fmtInt(inv.evidence.length)} items computed by deterministic tools. Click an id for the full computation.</div>
          </div>
        </div>
        {inv.evidence.length === 0 ? (
          <div className="px-5 py-6 text-base text-ink-400">No evidence recorded for this case.</div>
        ) : (
          <table className="table-base">
            <thead>
              <tr>
                <th>Id</th>
                <th>Title</th>
                <th>Metric</th>
                <th>Observed</th>
                <th>Comparison</th>
                <th>Δ</th>
                <th>z</th>
                <th>Quality</th>
                <th>Kind</th>
              </tr>
            </thead>
            <tbody>
              {inv.evidence.map((e) => (
                <tr key={e.evidence_id} className="cursor-pointer hover:bg-ink-800/60" onClick={() => onOpen(e.evidence_id)}>
                  <td className="font-mono text-blue-700">{e.evidence_id}</td>
                  <td>{e.title}</td>
                  <td className="font-mono text-sm">
                    {e.metric} <span className="text-ink-400">{e.unit}</span>
                  </td>
                  <td className="font-mono">{fmtNum(e.observed_stat, 2)}</td>
                  <td className="font-mono">{fmtNum(e.comparison_stat, 2)}</td>
                  <td className="font-mono">{fmtSigned(e.delta, 2)}</td>
                  <td className="font-mono">{fmtNum(e.z_score, 2)}</td>
                  <td>
                    <span className={`font-semibold uppercase ${e.data_quality === "pass" ? "text-green-800" : e.data_quality === "warn" ? "text-amber-800" : "text-red-800"}`}>{e.data_quality}</span>
                  </td>
                  <td className="text-sm">
                    {e.is_synthetic ? <span className="font-semibold text-amber-800">synthetic</span> : <span className="text-ink-300">{humanize(e.kind)}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* agent timeline */}
      <div className="panel mb-5 overflow-hidden">
        <div className="panel-header">
          <div>
            <div className="panel-title">Agent timeline</div>
            <div className="mt-0.5 text-sm text-ink-300">Tool events, not hidden reasoning. {inv.meta_used ? `Model: ${inv.meta_model}.` : "No Meta inference was used."}</div>
          </div>
          <span className="font-mono text-sm text-ink-400">{inv.events.length} events</span>
        </div>
        <AgentTimeline events={inv.events} evidenceById={evidenceById} onOpenEvidence={onOpen} />
      </div>

      <ReviewPanel investigation={inv} onReviewed={setInv} />

      <div className="mt-5">
        <PrecedentsPanel caseId={inv.case_id} />
      </div>
      <div className="mt-5">
        <CaseActivityFeed caseId={inv.case_id} />
      </div>
      <div className="mt-5">
        <DominoMap caseId={inv.case_id} />
      </div>
      <div className="mt-5">
        <WhatIfConsole caseId={inv.case_id} />
      </div>

      <EvidenceDrawer evidence={openEvidence ? (evidenceById.get(openEvidence) ?? null) : null} missingId={missingEvidence} onClose={onClose} />
    </div>
  );
}
