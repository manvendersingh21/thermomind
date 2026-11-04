import { ArrowRight, Plus, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { listInvestigations } from "../api/client";
import { ErrorBanner, PanelSkeleton } from "../components/Feedback";
import { PageHeader } from "../components/Layout";
import { SourceBadge } from "../components/SourceBadge";
import { InvestigationStatusPill, SeverityPill } from "../components/StatusPill";
import { useAsync } from "../hooks/useAsync";
import { fmtDateTime, rangeLabel } from "../lib/format";

export function InvestigationsPage() {
  const inv = useAsync((s) => listInvestigations(s), []);
  const list = inv.data ?? [];

  return (
    <div>
      <PageHeader
        title="Investigations"
        subtitle="Every case is a draft that requires human review. Reports cite evidence IDs produced by deterministic tools; nothing here can act on the plant."
        right={
          <Link to="/" className="btn-primary">
            <Plus size={18} /> New investigation
          </Link>
        }
      />
      {inv.error ? <ErrorBanner title="Could not load investigations" error={inv.error} onRetry={inv.reload} /> : null}
      {inv.loading ? <PanelSkeleton lines={6} /> : null}
      {!inv.loading && !inv.error && list.length === 0 ? (
        <div className="panel flex flex-col items-center gap-3 px-6 py-12 text-center">
          <Search size={30} className="text-ink-400" />
          <div className="text-lg font-semibold">No investigations yet</div>
          <p className="max-w-md text-base text-ink-300">Pick a window and scenario on the Overview page and run a diagnostic investigation.</p>
          <Link to="/" className="btn-secondary mt-2">
            Go to Overview <ArrowRight size={16} />
          </Link>
        </div>
      ) : null}
      {list.length > 0 ? (
        <div className="panel overflow-hidden">
          <table className="table-base">
            <thead>
              <tr>
                <th>Case</th>
                <th>Scenario</th>
                <th>Window</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Severity</th>
                <th>Created</th>
                <th>Reviewed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((i) => (
                <tr key={i.case_id} className="hover:bg-ink-800/60">
                  <td>
                    <Link to={`/investigations/${i.case_id}`} className="font-mono text-blue-700 hover:underline">
                      {i.case_id}
                    </Link>
                    {i.report ? <div className="mt-0.5 max-w-xs truncate text-sm text-ink-300">{i.report.title}</div> : null}
                  </td>
                  <td>
                    <div className="flex flex-col gap-1">
                      <span className="text-ink-100">{i.scenario.title}</span>
                      {i.scenario_label === "synthetic_overlay" ? <SourceBadge variant="synthetic" size="sm" /> : <SourceBadge variant="real" size="sm" />}
                    </div>
                  </td>
                  <td className="font-mono text-sm text-ink-200">{rangeLabel(i.window)}</td>
                  <td>
                    {i.mode === "meta_live" ? (
                      <SourceBadge variant="meta" size="sm" label={`META LIVE · ${i.meta_model ?? "muse-spark-1.3"}`} />
                    ) : (
                      <SourceBadge variant="offline" size="sm" label="OFFLINE PREVIEW" />
                    )}
                  </td>
                  <td>
                    <InvestigationStatusPill status={i.status} />
                  </td>
                  <td>{i.report ? <SeverityPill severity={i.report.severity} /> : <span className="text-ink-400">—</span>}</td>
                  <td className="whitespace-nowrap text-sm text-ink-300">{fmtDateTime(i.created_at_utc)}</td>
                  <td className="text-sm">
                    {i.review ? (
                      <span className="text-green-800">
                        {i.review.decision.replace(/_/g, " ")} · {i.review.reviewer}
                      </span>
                    ) : (
                      <span className="text-amber-800">awaiting review</span>
                    )}
                  </td>
                  <td>
                    <Link to={`/investigations/${i.case_id}`} className="text-ink-300 hover:text-blue-700">
                      <ArrowRight size={18} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
