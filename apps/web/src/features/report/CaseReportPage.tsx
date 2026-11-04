import { ArrowLeft, Printer } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { getInvestigation } from "../../api/client";
import type { Evidence, Hypothesis, Investigation } from "../../api/types";
import { ErrorBanner, PanelSkeleton } from "../../components/Feedback";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtDateTime, fmtNum, humanize, rangeLabel } from "../../lib/format";
import "./report.css";

function Section({ title, className = "", children }: { title: string; className?: string; children: ReactNode }) {
  return (
    <section className={`tm-section ${className}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Ids({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="tm-muted">none</span>;
  return <span className="tm-mono">{ids.join(", ")}</span>;
}

function List({ items, empty = "none" }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <p className="tm-muted">{empty}</p>;
  return (
    <ul>
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

function provenanceLabel(ev: Evidence): string {
  return `${humanize(ev.kind)}${ev.is_synthetic ? " (synthetic)" : ""}`;
}

function HypothesisBlock({ h }: { h: Hypothesis }) {
  return (
    <div className="tm-hyp">
      <h3>
        #{h.rank} {h.name} <span className="tm-muted">[{h.status.replace(/_/g, " ")}]</span>
      </h3>
      {h.rationale ? <p>{h.rationale}</p> : null}
      <dl>
        <dt>Supporting evidence</dt>
        <dd>
          <Ids ids={h.supporting_evidence_ids} />
        </dd>
        <dt>Contradicting evidence</dt>
        <dd>
          <Ids ids={h.contradicting_evidence_ids} />
        </dd>
        {h.limitations.length > 0 ? (
          <>
            <dt>Limitations</dt>
            <dd>
              <List items={h.limitations} />
            </dd>
          </>
        ) : null}
        {h.what_would_change_assessment ? (
          <>
            <dt>What would change the assessment</dt>
            <dd>{h.what_would_change_assessment}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function ReportBody({ inv }: { inv: Investigation }) {
  const report = inv.report;
  const dq = inv.data_quality;
  const b = inv.baseline;
  const toolEvents = inv.events.filter((e) => e.kind === "tool_call" || e.kind === "tool_result");
  const synthetic = inv.scenario_label === "synthetic_overlay";
  const hypotheses = report ? [...report.hypotheses].sort((x, y) => x.rank - y.rank) : [];

  return (
    <article className="tm-report">
      <div className="tm-toolbar no-print">
        <Link to={`/investigations/${encodeURIComponent(inv.case_id)}`} className="tm-btn">
          <ArrowLeft size={14} aria-hidden="true" /> Back to case
        </Link>
        <button type="button" className="tm-btn tm-btn-primary" onClick={() => window.print()}>
          <Printer size={14} aria-hidden="true" /> Print / Save as PDF
        </button>
      </div>

      <header className="tm-header">
        <div className="tm-kicker">ThermoMind case report</div>
        <h1>{report?.title ?? `Case ${inv.case_id}`}</h1>
        <div className="tm-badges">
          <SourceBadge variant="real" size="sm" />
          {synthetic ? <SourceBadge variant="synthetic" size="sm" /> : null}
          <SourceBadge variant={inv.mode === "meta_live" ? "meta" : "offline"} size="sm" />
          <SourceBadge variant="review" size="sm" />
        </div>
        <dl className="tm-meta">
          <dt>Case id</dt>
          <dd className="tm-mono">{inv.case_id}</dd>
          <dt>Status</dt>
          <dd>{humanize(inv.status)}</dd>
          <dt>Created</dt>
          <dd>{fmtDateTime(inv.created_at_utc)}</dd>
          <dt>Scenario</dt>
          <dd>
            {inv.scenario.scenario_id} &mdash; {inv.scenario.title}
          </dd>
          <dt>Window</dt>
          <dd>{rangeLabel(inv.window)}</dd>
          <dt>Reference</dt>
          <dd>{rangeLabel(inv.reference)}</dd>
          <dt>Baseline model</dt>
          <dd className="tm-mono">{inv.model_version ?? "—"}</dd>
          <dt>Mode</dt>
          <dd>
            {inv.mode === "meta_live" ? `Live model run (${inv.meta_model ?? "model id not recorded"})` : "Offline preview (no Meta inference)"}
          </dd>
          {report ? (
            <>
              <dt>Severity</dt>
              <dd>{humanize(report.severity)} (review priority)</dd>
              <dt>Data source</dt>
              <dd>{report.data_source}</dd>
            </>
          ) : null}
        </dl>
      </header>

      {inv.error ? <p className="tm-note">Case error: {inv.error}</p> : null}
      {inv.validation_errors.length > 0 ? (
        <p className="tm-note">Validation messages: {inv.validation_errors.join(" | ")}</p>
      ) : null}

      {report ? (
        <>
          <Section title="Summary">
            <p>{report.summary}</p>
          </Section>

          <Section title="Ranked hypotheses">
            {hypotheses.length === 0 ? <p className="tm-muted">none</p> : hypotheses.map((h) => <HypothesisBlock key={`${h.rank}-${h.name}`} h={h} />)}
          </Section>

          <Section title="Observations">
            {report.observations.length === 0 ? (
              <p className="tm-muted">none</p>
            ) : (
              <ol>
                {report.observations.map((o, i) => (
                  <li key={i}>
                    {o.statement} <span className="tm-muted">[</span>
                    <Ids ids={o.evidence_ids} />
                    <span className="tm-muted">]</span>
                  </li>
                ))}
              </ol>
            )}
          </Section>
        </>
      ) : (
        <Section title="Summary">
          <p className="tm-muted">No diagnostic report has been produced for this case (status: {inv.status}).</p>
        </Section>
      )}

      <Section title="Evidence ledger" className="tm-break">
        {inv.evidence.length === 0 ? (
          <p className="tm-muted">No evidence recorded.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Metric</th>
                <th>Unit</th>
                <th>Sample range</th>
                <th className="tm-num">Observed</th>
                <th className="tm-num">Comparison</th>
                <th className="tm-num">z</th>
                <th>Method</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {inv.evidence.map((ev) => (
                <tr key={ev.evidence_id}>
                  <td className="tm-mono">{ev.evidence_id}</td>
                  <td>{ev.metric}</td>
                  <td>{ev.unit}</td>
                  <td>{rangeLabel(ev.sample_range)}</td>
                  <td className="tm-num">{fmtNum(ev.observed_stat, 3)}</td>
                  <td className="tm-num">{fmtNum(ev.comparison_stat, 3)}</td>
                  <td className="tm-num">{fmtNum(ev.z_score, 2)}</td>
                  <td>{ev.method}</td>
                  <td>{provenanceLabel(ev)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Data quality" className="tm-break">
        {dq ? (
          <dl className="tm-meta">
            <dt>Scenario label</dt>
            <dd>{humanize(dq.scenario_label)}</dd>
            <dt>Source</dt>
            <dd>{dq.source}</dd>
            <dt>Synthetic measurements</dt>
            <dd>{dq.synthetic_measurements.length ? dq.synthetic_measurements.join(", ") : "none"}</dd>
            <dt>Missing values</dt>
            <dd>
              {Object.keys(dq.missing_values).length
                ? Object.entries(dq.missing_values)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(", ")
                : "none recorded"}
            </dd>
            <dt>Out of training range</dt>
            <dd>
              {Object.keys(dq.out_of_training_range).length
                ? Object.entries(dq.out_of_training_range)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(", ")
                : "none recorded"}
            </dd>
            <dt>Sensor consistency flags</dt>
            <dd>{dq.sensor_consistency_flags.length ? dq.sensor_consistency_flags.join(", ") : "none"}</dd>
            {dq.notes.length > 0 ? (
              <>
                <dt>Notes</dt>
                <dd>
                  <List items={dq.notes} />
                </dd>
              </>
            ) : null}
          </dl>
        ) : (
          <p className="tm-muted">No data-quality report recorded.</p>
        )}
      </Section>

      <Section title="Baseline comparison">
        {b ? (
          <>
            <table>
              <tbody>
                <tr>
                  <th>Observed TEY mean</th>
                  <td className="tm-num">
                    {fmtNum(b.observed_tey_mean, 3)} {b.unit}
                  </td>
                </tr>
                <tr>
                  <th>Expected TEY mean (model)</th>
                  <td className="tm-num">
                    {fmtNum(b.expected_tey_mean, 3)} {b.unit}
                  </td>
                </tr>
                <tr>
                  <th>Residual mean</th>
                  <td className="tm-num">
                    {fmtNum(b.residual_mean, 3)} {b.unit}
                  </td>
                </tr>
                <tr>
                  <th>Residual z</th>
                  <td className="tm-num">{fmtNum(b.residual_z, 2)}</td>
                </tr>
                <tr>
                  <th>Reference residual mean</th>
                  <td className="tm-num">
                    {fmtNum(b.reference_residual_mean, 3)} {b.unit}
                  </td>
                </tr>
                <tr>
                  <th>Holdout MAE / R&sup2; (model)</th>
                  <td className="tm-num">
                    {fmtNum(b.holdout_mae, 3)} {b.unit} / {fmtNum(b.holdout_r2, 3)}
                  </td>
                </tr>
                <tr>
                  <th>Model version</th>
                  <td className="tm-mono">{b.model_version}</td>
                </tr>
              </tbody>
            </table>
            <h3>Caveats</h3>
            <List items={b.caveats} />
          </>
        ) : (
          <p className="tm-muted">No baseline comparison recorded.</p>
        )}
      </Section>

      {report ? (
        <Section title="Limitations and next checks">
          <h3>Limitations</h3>
          <List items={report.limitations} />
          <h3>Additional data needed</h3>
          <List items={report.additional_data_needed} />
          <h3>Engineer review checks</h3>
          <List items={report.engineer_review_checks} />
        </Section>
      ) : null}

      <Section title="Agent tool events" className="tm-break">
        {toolEvents.length === 0 ? (
          <p className="tm-muted">No tool events recorded.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th className="tm-num">#</th>
                <th>Event</th>
                <th>Tool</th>
                <th>Evidence ids</th>
              </tr>
            </thead>
            <tbody>
              {toolEvents.map((e) => (
                <tr key={e.seq}>
                  <td className="tm-num">{e.seq}</td>
                  <td>{e.kind.replace(/_/g, " ")}</td>
                  <td className="tm-mono">{e.tool_name ?? "—"}</td>
                  <td>
                    <Ids ids={e.evidence_ids} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Review record">
        {inv.review ? (
          <dl className="tm-meta">
            <dt>Decision</dt>
            <dd>{humanize(inv.review.decision)}</dd>
            <dt>Reviewer</dt>
            <dd>{inv.review.reviewer}</dd>
            <dt>Recorded</dt>
            <dd>{fmtDateTime(inv.review.ts_utc)}</dd>
            <dt>Comment</dt>
            <dd>{inv.review.comment ?? "—"}</dd>
          </dl>
        ) : (
          <p>Not yet reviewed. This report is a draft that requires human review.</p>
        )}
      </Section>

      <footer className="tm-footer">
        <p>
          <strong>Disclaimer.</strong>{" "}
          {report?.disclaimer ??
            "Draft decision support only. Requires review by a qualified engineer. ThermoMind is read-only and issues no control commands."}
        </p>
        <p>
          Report status: draft_requires_human_review. Data: UCI Gas Turbine CO and NOx Emission Data Set (CC BY 4.0); rows carry sample indices, not timestamps.
        </p>
        <p>
          Report hash: <span className="tm-mono tm-hash">{inv.report_hash ?? "not available"}</span>
        </p>
      </footer>
    </article>
  );
}

export default function CaseReportPage() {
  const { caseId = "" } = useParams();
  const { data, error, loading, reload } = useAsync((signal) => getInvestigation(caseId, signal), [caseId]);

  if (loading) return <div className="tm-report-wrap"><PanelSkeleton lines={8} /></div>;
  if (error || !data) {
    return (
      <div className="tm-report-wrap">
        <ErrorBanner error={error ?? new Error("Case not found")} title="Could not load case report" onRetry={reload} />
        <p className="mt-3">
          <Link to="/investigations" className="underline">
            Back to investigations
          </Link>
        </p>
      </div>
    );
  }
  return (
    <div className="tm-report-wrap">
      <ReportBody inv={data} />
    </div>
  );
}
