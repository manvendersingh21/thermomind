import { BookOpen, Cpu, FlaskConical, Map, MonitorCog, ShieldAlert, Sigma } from "lucide-react";
import { getDemoStatus, getModelComparison, getModelEvaluation, isApiError } from "../api/client";
import type { MetricSet, ModelEvaluation } from "../api/types";
import { ErrorBanner, InfoBanner, PanelSkeleton, WarnBanner } from "../components/Feedback";
import { PageHeader } from "../components/Layout";
import { SourceBadge } from "../components/SourceBadge";
import { useAsync } from "../hooks/useAsync";
import { fmtDateTime, fmtInt, fmtNum, fmtSigned, humanize } from "../lib/format";

function MetricRow({ name, m, highlight = false }: { name: string; m: MetricSet; highlight?: boolean }) {
  return (
    <tr className={highlight ? "bg-green-50/70" : ""}>
      <td className={highlight ? "font-semibold text-green-800" : ""}>{name}</td>
      <td className="text-right font-mono">{fmtNum(m.mae, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.rmse, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.r2, 4)}</td>
      <td className="text-right font-mono">{fmtInt(m.n)}</td>
    </tr>
  );
}

function KV({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj);
  if (entries.length === 0) return <div className="text-sm text-ink-400">—</div>;
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-950">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 border-b border-ink-800 px-3 py-1.5 font-mono text-sm last:border-b-0">
          <span className="text-ink-300">{k}</span>
          <span className="max-w-[60%] break-words text-right text-ink-100">{typeof v === "string" ? v : JSON.stringify(v)}</span>
        </div>
      ))}
    </div>
  );
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

function ComparisonRow({ m, production }: { m: ModelEvaluation; production: boolean }) {
  return (
    <tr className={production ? "bg-green-50/70" : ""}>
      <td>
        <div className="font-semibold text-ink-50">{m.model_version}</div>
        <div className="font-mono text-sm text-ink-400">{m.model_id} · {m.algorithm}</div>
        <div className="mt-1">
          {production ? (
            <SourceBadge variant="real" size="sm" label="PRODUCTION BASELINE" />
          ) : (
            <SourceBadge variant="offline" size="sm" label={humanize(m.role ?? "challenger").toUpperCase()} />
          )}
        </div>
      </td>
      <td className="text-right font-mono">{fmtNum(m.validation.mae, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.validation.rmse, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.validation.r2, 4)}</td>
      <td className="text-right font-mono">{fmtNum(m.holdout.mae, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.holdout.rmse, 3)}</td>
      <td className="text-right font-mono">{fmtNum(m.holdout.r2, 4)}</td>
      <td className="font-mono text-sm">{m.device ?? "—"}</td>
      <td className="text-right font-mono">{m.training_seconds !== null && m.training_seconds !== undefined ? `${fmtNum(m.training_seconds, 1)} s` : "—"}</td>
    </tr>
  );
}

export function EvaluationPage() {
  const evalState = useAsync((s) => getModelEvaluation(s), []);
  const demo = useAsync((s) => getDemoStatus(s), []);
  const comparison = useAsync((s) => getModelComparison(s), []);
  // 404 = endpoint not wired / no challengers yet: hide the section silently.
  const comparisonHidden = isApiError(comparison.error) && comparison.error.status === 404;
  const ev = evalState.data;
  const notTrained = isApiError(evalState.error) && evalState.error.status === 404;

  return (
    <div>
      <PageHeader
        title="Evaluation & Trust"
        subtitle="How the baseline model is measured, how synthetic scenarios behave, and what this prototype must never be used for."
        right={
          <>
            <SourceBadge variant="model" />
            <SourceBadge variant="review" label="EXPERIMENTAL PROTOTYPE" />
          </>
        }
      />

      {evalState.loading ? <PanelSkeleton lines={6} className="mb-5" /> : null}
      {notTrained ? (
        <WarnBanner className="mb-5">
          Baseline model not trained — run <code className="font-mono text-amber-800">make train</code> from the repository root. Metrics are only ever reported from actual
          training runs; nothing is shown until then.
        </WarnBanner>
      ) : evalState.error ? (
        <ErrorBanner className="mb-5" title="Could not load model evaluation" error={evalState.error} onRetry={evalState.reload} />
      ) : null}

      {ev ? (
        <>
          <div className="mb-5 grid grid-cols-3 gap-4">
            <div className="panel col-span-2 overflow-hidden">
              <div className="panel-header">
                <div>
                  <div className="panel-title">Baseline model — expected TEY</div>
                  <div className="mt-0.5 text-sm text-ink-300">
                    <span className="font-mono text-ink-100">{ev.model_id}</span> · {ev.model_version} · {ev.algorithm} · seed {ev.seed} · trained {fmtDateTime(ev.trained_at_utc)}
                    {ev.device ? ` · ${ev.device}` : ""}
                    {ev.training_seconds !== null && ev.training_seconds !== undefined ? ` · ${fmtNum(ev.training_seconds, 1)} s` : ""}
                    {ev.role ? ` · ${humanize(ev.role)}` : ""}
                  </div>
                </div>
                <SourceBadge variant="model" size="sm" />
              </div>
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Split / baseline</th>
                    <th className="text-right">MAE ({ev.target_unit})</th>
                    <th className="text-right">RMSE ({ev.target_unit})</th>
                    <th className="text-right">R²</th>
                    <th className="text-right">n</th>
                  </tr>
                </thead>
                <tbody>
                  <MetricRow name={`Validation (${ev.split.validation_years.join(", ")})`} m={ev.validation} highlight />
                  <MetricRow name={`Holdout (${ev.split.test_years.join(", ")}, untouched)`} m={ev.holdout} highlight />
                  {Object.entries(ev.naive_baselines).map(([k, m]) => (
                    <MetricRow key={k} name={`Naive: ${humanize(k)} (holdout)`} m={m} />
                  ))}
                </tbody>
              </table>
              <div className="border-t border-ink-700 px-5 py-3 text-sm text-ink-300">
                Split method <span className="font-mono text-ink-100">{ev.split.method}</span>: train {ev.split.train_years.join("/")} ({fmtInt(ev.split.train_rows)} rows) → validation{" "}
                {ev.split.validation_years.join("/")} ({fmtInt(ev.split.validation_rows)}) → holdout {ev.split.test_years.join("/")} ({fmtInt(ev.split.test_rows)}). Target {ev.target} in{" "}
                {ev.target_unit} as published (not converted to MW).
              </div>
            </div>
            <div className="space-y-4">
              <Section title="Residual quantiles (validation)" icon={<Sigma size={18} className="text-green-800" />}>
                <table className="table-base">
                  <tbody>
                    {Object.entries(ev.residual_quantiles_validation).map(([q, v]) => (
                      <tr key={q}>
                        <td className="font-mono">{q}</td>
                        <td className="text-right font-mono">
                          {fmtSigned(v, 3)} {ev.target_unit}
                        </td>
                      </tr>
                    ))}
                    <tr>
                      <td className="font-mono text-ink-300">residual std</td>
                      <td className="text-right font-mono">
                        {fmtNum(ev.residual_std_validation, 3)} {ev.target_unit}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div className="mt-2 text-sm text-ink-400">observed − expected; used to scale residual z-scores in evidence.</div>
              </Section>
            </div>
          </div>

          <div className="mb-5 grid grid-cols-2 gap-4">
            <Section title="Features & training ranges" icon={<Cpu size={18} className="text-ink-300" />}>
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Feature</th>
                    <th className="text-right">Train min</th>
                    <th className="text-right">Train max</th>
                  </tr>
                </thead>
                <tbody>
                  {ev.features.map((f) => (
                    <tr key={f}>
                      <td className="font-mono text-blue-700">{f}</td>
                      <td className="text-right font-mono">{fmtNum(ev.feature_ranges_train[f]?.[0] ?? null, 2)}</td>
                      <td className="text-right font-mono">{fmtNum(ev.feature_ranges_train[f]?.[1] ?? null, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-2 text-sm text-ink-400">Rows outside these ranges are flagged out_of_training_range in evidence.</div>
            </Section>
            <Section title="Model notes" icon={<BookOpen size={18} className="text-ink-300" />}>
              {ev.notes.length === 0 ? (
                <div className="text-base text-ink-400">No notes recorded by the training run.</div>
              ) : (
                <ul className="list-disc space-y-1.5 pl-5 text-base text-ink-100">
                  {ev.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        </>
      ) : null}

      {!comparisonHidden && (comparison.loading || comparison.error || comparison.data) ? (
        <div className="panel mb-5 overflow-hidden">
          <div className="panel-header">
            <div>
              <div className="panel-title flex items-center gap-2">
                <MonitorCog size={18} className="text-green-800" /> Production baseline vs GPU challenger
              </div>
              <div className="mt-0.5 text-sm text-ink-300">
                Same chronological split for every model; the production model is selected on validation only — holdout is never used for selection.
              </div>
            </div>
            {comparison.data ? (
              <span className={`text-sm font-semibold ${comparison.data.gpu.available ? "text-green-800" : "text-ink-400"}`}>
                GPU {comparison.data.gpu.available ? `available · ${comparison.data.gpu.name ?? "unnamed"}` : "not available"}
                {comparison.data.gpu.memory_mb ? ` · ${fmtInt(Math.round(comparison.data.gpu.memory_mb))} MB` : ""}
                {comparison.data.gpu.driver ? ` · driver ${comparison.data.gpu.driver}` : ""}
              </span>
            ) : null}
          </div>
          {comparison.loading ? (
            <div className="p-5">
              <PanelSkeleton lines={3} />
            </div>
          ) : null}
          {comparison.error && !comparison.loading ? (
            <div className="p-5">
              <ErrorBanner title="Could not load model comparison" error={comparison.error} onRetry={comparison.reload} />
            </div>
          ) : null}
          {comparison.data ? (
            <>
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th className="text-right">Val MAE</th>
                    <th className="text-right">Val RMSE</th>
                    <th className="text-right">Val R²</th>
                    <th className="text-right">Holdout MAE</th>
                    <th className="text-right">Holdout RMSE</th>
                    <th className="text-right">Holdout R²</th>
                    <th>Device</th>
                    <th className="text-right">Training</th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow m={comparison.data.production} production />
                  {comparison.data.challengers.map((c) => (
                    <ComparisonRow key={c.model_version + c.model_id} m={c} production={false} />
                  ))}
                </tbody>
              </table>
              <div className="border-t border-ink-700 px-5 py-3 text-sm text-ink-300">
                <span className="font-semibold text-ink-100">Selection rule:</span> {comparison.data.selection_rule}
                {comparison.data.challengers.length === 0 ? " · No challengers trained yet." : ""}
                {" "}Metrics in {comparison.data.production.target_unit}; all values come from executed training runs.
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      <div className="mb-5 rounded-xl border border-amber-300 bg-amber-50/70 p-5">
        <div className="mb-2 flex items-center gap-2">
          <FlaskConical size={20} className="text-amber-700" />
          <h2 className="text-lg font-semibold text-amber-800">Synthetic scenario behaviour</h2>
          <SourceBadge variant="synthetic" size="sm" />
        </div>
        <div className="grid grid-cols-2 gap-5 text-base text-ink-100">
          <div className="space-y-2">
            <p>
              Scenarios S02–S04 apply parameterised, seeded transformations (ramps, offsets, step segments) to a <em>copy</em> of the real rows in the case window.
              Original rows are never mutated, the reference window is always real, and every series, evidence item and report carries{" "}
              <code className="font-mono text-amber-800">synthetic=true</code> / <code className="font-mono text-amber-800">scenario_label=synthetic_overlay</code>.
            </p>
            <p>
              S01 is the control: unmodified real data. Its purpose is to check the pipeline does <strong>not</strong> invent faults. The dataset contains no verified fault
              labels, so a synthetic overlay is an illustration of a documented physical tendency, not a recorded event at the source plant.
            </p>
            <p>
              The agent never sees a scenario's <code className="font-mono">expected_behavior</code> text; it only receives tool outputs and may only cite evidence ids
              that those tools returned. Cited ids are validated server-side; unknown ids fail validation and trigger one bounded rewrite.
            </p>
          </div>
          <div>
            <div className="label mb-2">Scenario registry status (from /api/demo/status)</div>
            {demo.loading ? <PanelSkeleton lines={3} /> : null}
            {demo.error ? <ErrorBanner title="Could not load demo status" error={demo.error} onRetry={demo.reload} /> : null}
            {demo.data ? (
              <>
                <KV obj={demo.data.scenarios} />
                <div className="mt-3 text-sm text-ink-400">Scenario robustness is reported only from executed runs; nothing here is a claimed result.</div>
              </>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-4">
        <Section title="Architecture" icon={<Cpu size={18} className="text-blue-700" />}>
          <ol className="list-decimal space-y-2 pl-5 text-base text-ink-100">
            <li>
              <strong>Read-only data layer.</strong> UCI rows loaded with source_year + row_index only; no timestamps fabricated; sha256 per source file.
            </li>
            <li>
              <strong>Deterministic evidence layer.</strong> Window-vs-reference statistics, z-scores, trend slopes, data-quality checks and baseline TEY residuals, each
              emitted as an Evidence item with its computation string.
            </li>
            <li>
              <strong>Meta Muse Spark tool loop.</strong> <code className="font-mono">muse-spark-1.3</code> (OpenAI-compatible Meta Model API) is given tools
              (get_sensor_window, get_baseline_comparison, evaluate_hypothesis, get_data_quality, lookup_reference) and must do its work through them. Key stays server-side.
            </li>
            <li>
              <strong>Validator.</strong> Structured report schema, evidence-id citation check, scenario-label consistency, one bounded rewrite; otherwise needs_review with the
              deterministic summary.
            </li>
            <li>
              <strong>Human review.</strong> Every report is <code className="font-mono">draft_requires_human_review</code>; an engineer records accept / reject / more data.
            </li>
          </ol>
        </Section>
        <div className="space-y-4">
          <Section title="Safety disclaimer" icon={<ShieldAlert size={18} className="text-amber-700" />}>
            <p className="text-base text-ink-100">
              ThermoMind is an experimental engineering decision-support prototype. It is <strong>not</strong> a validated diagnostic, protection, safety or control system. It
              has no connection to any PLC, SCADA, DCS or historian, writes no setpoints and issues no commands. Outputs are drafts for qualified engineers and must not be used
              as the sole basis for operational decisions.
            </p>
          </Section>
          <Section title="Backend / Meta status" icon={<Cpu size={18} className="text-ink-300" />}>
            {demo.data ? (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="label mb-1">Model</div>
                  <KV obj={demo.data.model} />
                </div>
                <div>
                  <div className="label mb-1">Meta</div>
                  <KV obj={demo.data.meta} />
                </div>
                <div className="col-span-2">
                  {demo.data.ready_for_demo ? (
                    <InfoBanner>Demo readiness: ready.</InfoBanner>
                  ) : (
                    <WarnBanner>
                      Demo readiness blockers:
                      <ul className="list-disc pl-4">
                        {demo.data.blockers.map((b, i) => (
                          <li key={i}>{b}</li>
                        ))}
                      </ul>
                    </WarnBanner>
                  )}
                </div>
              </div>
            ) : demo.loading ? (
              <PanelSkeleton lines={3} />
            ) : (
              <div className="text-sm text-ink-400">unavailable</div>
            )}
          </Section>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Section title="Attributions" icon={<BookOpen size={18} className="text-ink-300" />}>
          <ul className="space-y-2 text-base text-ink-100">
            <li>
              <strong>Data:</strong> Kaya, H., Tüfekci, P. & Gürgen, F. (2019). Gas Turbine CO and NOx Emission Data Set. UCI Machine Learning Repository.{" "}
              <a href="https://doi.org/10.24432/C5WC95" target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">
                DOI 10.24432/C5WC95
              </a>{" "}
              · CC BY 4.0.
            </li>
            <li>
              <strong>Model inference:</strong> Meta Model API, <code className="font-mono">muse-spark-1.3</code> (only when configured; otherwise offline preview).
            </li>
            <li>
              <strong>Baseline:</strong> scikit-learn gradient boosting, trained locally; metrics above come from the actual training run.
            </li>
          </ul>
        </Section>
        <Section title="Roadmap (future — not implemented)" icon={<Map size={18} className="text-ink-300" />}>
          <ul className="list-disc space-y-1.5 pl-5 text-base text-ink-100">
            <li>EPA CAMPD emissions/operations data as an additional public source (future).</li>
            <li>Historian exports (PI/OSIsoft, Honeywell PHD) with real timestamps and tag metadata (future).</li>
            <li>Verified fault labels from maintenance records to evaluate hypothesis ranking (future).</li>
            <li>Per-unit baselines and seasonal reference windows (future).</li>
          </ul>
        </Section>
      </div>
    </div>
  );
}
