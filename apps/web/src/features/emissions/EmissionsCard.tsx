import { ArrowRight, Wind } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorBanner, PanelSkeleton } from "../../components/Feedback";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtInt, fmtNum } from "../../lib/format";
import { getEmissionsOverview, getEmissionsWindow } from "./api";

interface Props {
  year: number;
  datasetId?: string;
  /** Optional [start, end) window; whole year when omitted. */
  start?: number;
  end?: number;
  className?: string;
}

/** Compact emissions-watch card for embedding on the Overview. Screening only. */
export function EmissionsCard({ year, datasetId = "ds_uci_551", start, end, className = "" }: Props) {
  const windowed = start !== undefined && end !== undefined;
  const state = useAsync(
    (signal) =>
      windowed
        ? getEmissionsWindow({ dataset_id: datasetId, year, start: start as number, end: end as number }, signal)
        : getEmissionsOverview({ dataset_id: datasetId, year }, signal),
    [datasetId, year, start, end, windowed],
  );
  const d = state.data;

  if (state.loading) return <PanelSkeleton lines={3} className={className} />;
  if (state.error) return <ErrorBanner className={className} title="Emissions watch unavailable" error={state.error} onRetry={state.reload} />;
  if (!d) return null;

  const k = d.kpis;
  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div className="panel-title flex items-center gap-2">
          <Wind size={18} className="text-ink-400" />
          Emissions watch · CO / NOX
        </div>
        <SourceBadge variant="real" size="sm" label="REAL MEASUREMENTS" />
      </div>
      <div className="grid grid-cols-3 gap-4 px-5 py-4">
        <div>
          <div className="label">Hours above threshold</div>
          <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink-50">{fmtInt(k.hours_above_any)}</div>
          <div className="text-sm text-ink-300">
            CO {fmtInt(k.hours_above_co)} · NOX {fmtInt(k.hours_above_nox)} of {fmtInt(k.rows_analyzed)} samples
          </div>
        </div>
        <div>
          <div className="label">Excursions (≥3 samples)</div>
          <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink-50">{fmtInt(k.excursions_total)}</div>
          <div className="text-sm text-ink-300">
            CO {k.excursions_co} · NOX {k.excursions_nox}
          </div>
        </div>
        <div>
          <div className="label">Corr. CO vs TEY</div>
          <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-ink-50">{fmtNum(k.corr_co_tey.spearman, 2)}</div>
          <div className="text-sm text-ink-300">Spearman · AT {fmtNum(k.corr_co_at.spearman, 2)}</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
        <span>
          Screening only — thresholds = p95 of {d.source_year} (CO {fmtNum(d.thresholds.co, 2)}, NOX {fmtNum(d.thresholds.nox, 1)} mg/m³), not permit limits.
        </span>
        <Link to="/emissions" className="inline-flex items-center gap-1 font-semibold text-blue-700 hover:underline">
          Open emissions watch <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  );
}

export default EmissionsCard;
