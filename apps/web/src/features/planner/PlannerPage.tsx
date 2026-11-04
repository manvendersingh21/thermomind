/**
 * Maintenance planner — route `/planner` (wire in App.tsx: `<Route path="/planner" element={<PlannerPage />} />`).
 * Two break-even planning aids computed from the real UCI data + the production baseline + user assumptions.
 */
import { CalendarClock, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { isApiError } from "../../api/client";
import { ErrorBanner, PanelSkeleton, WarnBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { getPlannerOptions } from "./api";
import { CompressorWashCard } from "./components/CompressorWashCard";
import { FilterChangeoutCard } from "./components/FilterChangeoutCard";

const DISCLAIMER =
  "Planning aid from historical data and your assumptions — not a maintenance instruction; schedule through site procedures.";

export default function PlannerPage() {
  const opts = useAsync((s) => getPlannerOptions(s), []);
  const [yearSel, setYearSel] = useState<number | null>(null);
  const o = opts.data;
  const year = yearSel ?? o?.default_year ?? null;

  return (
    <div>
      <PageHeader
        title="Maintenance Planner"
        subtitle="Compressor water-wash and inlet-filter change-out break-even, per source year, from the real UCI measurements, the production baseline model and your own economic assumptions."
        right={
          <>
            <SourceBadge variant="real" />
            <SourceBadge variant="model" />
            <SourceBadge variant="review" label="HUMAN REVIEW REQUIRED" />
          </>
        }
      />

      <div
        role="note"
        className="sticky top-0 z-10 mb-5 flex items-start gap-3 rounded-xl border border-yellow-400 bg-yellow-50 px-4 py-3 text-yellow-900 shadow-sm"
      >
        <ShieldAlert size={20} className="mt-0.5 shrink-0 text-yellow-700" />
        <div className="text-base font-semibold">{o?.disclaimer ?? DISCLAIMER}</div>
      </div>

      {opts.loading ? <PanelSkeleton lines={4} className="mb-5" /> : null}
      {opts.error && !(isApiError(opts.error) && opts.error.status === 404) ? (
        <ErrorBanner className="mb-5" title="Could not load planner options" error={opts.error} onRetry={opts.reload} />
      ) : null}

      {o ? (
        <>
          {!o.data_available ? (
            <WarnBanner className="mb-5">
              Dataset not loaded — run <code className="font-mono">make data</code> (or POST /api/datasets/seed-uci) and reload.
            </WarnBanner>
          ) : null}
          {!o.model_available ? (
            <WarnBanner className="mb-5">
              Baseline model not trained — run <code className="font-mono">make train</code>. The planner needs the production baseline for
              residuals and training-year associations.
            </WarnBanner>
          ) : null}

          <div className="mb-5 flex flex-wrap items-center gap-3 text-sm text-ink-300">
            <CalendarClock size={18} className="text-ink-400" />
            <label htmlFor="planner-year" className="font-medium text-ink-100">
              Source year
            </label>
            <select
              id="planner-year"
              className="input h-9 w-28"
              value={year ?? ""}
              onChange={(e) => setYearSel(Number(e.target.value))}
              disabled={o.years.length === 0}
            >
              {o.years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <span>
              Dataset <span className="font-mono text-ink-100">{o.dataset_id}</span> · model{" "}
              <span className="font-mono text-ink-100">{o.model_version ?? "—"}</span> · one row = one hourly sample, no timestamps
            </span>
          </div>

          {year !== null && o.data_available && o.model_available ? (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <CompressorWashCard key={`w-${year}`} datasetId={o.dataset_id} year={year} defaults={o.wash_defaults} />
              <FilterChangeoutCard
                key={`f-${year}`}
                datasetId={o.dataset_id}
                year={year}
                defaults={o.filter_defaults}
                trainingRange={o.afdp_training_range_mbar}
              />
            </div>
          ) : null}

          <p className="mt-5 text-sm text-ink-400">
            {o.notes.join(" ")} Outputs never estimate avoided downtime. Statuses such as “consider scheduling a wash (human decision)” flag an
            economic case under your assumptions only; the decision and scheduling remain with site engineering.
          </p>
        </>
      ) : null}
      {isApiError(opts.error) && opts.error.status === 404 ? (
        <WarnBanner>Planner API not available on this backend (route /api/planner not wired yet).</WarnBanner>
      ) : null}
    </div>
  );
}
