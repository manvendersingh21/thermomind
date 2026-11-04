import { Wind } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { listDatasets } from "../../api/client";
import { ChartSkeleton, ErrorBanner, InfoBanner, WarnBanner } from "../../components/Feedback";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtInt, fmtNum } from "../../lib/format";
import { getEmissionsOverview } from "./api";
import { COLORS, ProfileChart, ThresholdSeriesChart } from "./EmissionsCharts";
import type { EmissionsResponse } from "./types";

const DATASET_ID = "ds_uci_551";

function parseThreshold(s: string): number | undefined {
  if (s.trim() === "") return undefined;
  const v = Number(s);
  return Number.isFinite(v) && v > 0 ? v : undefined;
}

function ScreeningBadge({ title }: { title?: string }) {
  return (
    <span
      title={title ?? "Screening threshold, not a permit limit"}
      className="inline-flex items-center whitespace-nowrap rounded-md border border-yellow-400 bg-yellow-100 px-2 py-0.5 text-xs font-semibold tracking-wide text-yellow-900"
    >
      SCREENING
    </span>
  );
}

function ThresholdInput({
  label,
  value,
  onChange,
  placeholder,
  invalid,
  defaultValue,
  onReset,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  invalid: boolean;
  defaultValue: number | null;
  onReset: () => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="label flex items-center gap-2">
        {label} <ScreeningBadge />
      </span>
      <div className="flex items-center gap-2">
        <input
          className={`input w-32 font-mono ${invalid ? "border-red-400" : ""}`}
          inputMode="decimal"
          value={value}
          placeholder={placeholder}
          aria-invalid={invalid}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="text-sm text-ink-300">mg/m³</span>
        {value !== "" ? (
          <button type="button" className="text-sm font-semibold text-blue-700 hover:underline" onClick={onReset}>
            reset to p95{defaultValue !== null ? ` (${fmtNum(defaultValue, 2)})` : ""}
          </button>
        ) : (
          <span className="text-sm text-ink-400">default = p95 of year</span>
        )}
      </div>
      {invalid ? <span className="text-sm text-red-700">Enter a number &gt; 0 (or clear to use the default).</span> : null}
    </label>
  );
}

function corrText(c: { pearson: number | null; spearman: number | null }): string {
  return `Pearson ${fmtNum(c.pearson, 2)} · Spearman ${fmtNum(c.spearman, 2)}`;
}

/** One-sentence, data-derived statement of what the CO-vs-load profile shows (never assumed). */
function loadStatement(d: EmissionsResponse): string {
  const bins = d.profile_tey.filter((b) => b.co_median !== null);
  if (bins.length < 2) return "Not enough load bins in this window to describe CO vs load.";
  const lo = bins[0];
  const hi = bins[bins.length - 1];
  const a = lo.co_median as number;
  const b = hi.co_median as number;
  const rel = b > 0 ? a / b : NaN;
  const dir = a > b * 1.1 ? "higher at part load" : a < b * 0.9 ? "LOWER at part load" : "similar across load";
  return `In this selection median CO is ${fmtNum(a, 2)} mg/m³ in the lowest TEY decile (median TEY ${fmtNum(lo.tey_median, 1)}) vs ${fmtNum(b, 2)} mg/m³ in the highest (median TEY ${fmtNum(hi.tey_median, 1)})${Number.isFinite(rel) ? ` (${fmtNum(rel, 1)}×)` : ""}: CO is ${dir}.`;
}

export default function EmissionsPage() {
  const datasets = useAsync((s) => listDatasets(s), []);
  const years = useMemo(() => {
    const ds = datasets.data?.find((d) => d.dataset_id === DATASET_ID) ?? datasets.data?.[0];
    return ds?.years ?? [2011, 2012, 2013, 2014, 2015];
  }, [datasets.data]);

  const [year, setYear] = useState(2014);
  const [coText, setCoText] = useState("");
  const [noxText, setNoxText] = useState("");
  const [applied, setApplied] = useState<{ co?: number; nox?: number }>({});
  const [profileX, setProfileX] = useState<"tey" | "tit">("tey");

  const coVal = parseThreshold(coText);
  const noxVal = parseThreshold(noxText);
  const coInvalid = coText.trim() !== "" && coVal === undefined;
  const noxInvalid = noxText.trim() !== "" && noxVal === undefined;

  // debounce threshold edits so the API is not hit on every keystroke
  useEffect(() => {
    if (coInvalid || noxInvalid) return;
    const t = window.setTimeout(() => setApplied({ co: coVal, nox: noxVal }), 400);
    return () => window.clearTimeout(t);
  }, [coVal, noxVal, coInvalid, noxInvalid]);

  // changing year resets custom thresholds (p95 differs per year)
  function changeYear(y: number) {
    setYear(y);
    setCoText("");
    setNoxText("");
    setApplied({});
  }

  const q = useAsync(
    (signal) => getEmissionsOverview({ dataset_id: DATASET_ID, year, co_threshold: applied.co, nox_threshold: applied.nox }, signal),
    [year, applied.co, applied.nox],
  );
  const d = q.data;

  const coRows = useMemo(() => (d?.series ?? []).map((r) => ({ row_index: r.row_index, value: r.co })), [d]);
  const noxRows = useMemo(() => (d?.series ?? []).map((r) => ({ row_index: r.row_index, value: r.nox })), [d]);
  const coEx = useMemo(() => (d?.excursions ?? []).filter((e) => e.pollutant === "CO"), [d]);
  const noxEx = useMemo(() => (d?.excursions ?? []).filter((e) => e.pollutant === "NOX"), [d]);

  const customCo = d?.thresholds.co_source === "user";
  const customNox = d?.thresholds.nox_source === "user";

  return (
    <div>
      <PageHeader
        title="Emissions watch — CO and NOX screening"
        subtitle="Deterministic screening of the measured CO and NOX columns against load, turbine inlet temperature and ambient conditions. Read-only decision support."
        right={
          <>
            <SourceBadge variant="real" label="REAL UCI TURBINE DATA · CO/NOX AS MEASURED" />
            <ScreeningBadge />
          </>
        }
      />

      <WarnBanner className="mb-5">
        <strong>{d?.disclaimer ?? "Screening only; permit limits, averaging periods and CEMS QA/QC are site-specific; not a compliance determination."}</strong>{" "}
        {d?.target_note ??
          "CO and NOX are real measurements (mg/m³, as published). The UCI paper used them as prediction targets; here they are used as measurements only."}
      </WarnBanner>

      <div className="panel mb-6">
        <div className="panel-header">
          <div className="panel-title">Selection and screening thresholds</div>
          <div className="text-sm text-ink-300">
            {d ? `${d.source_year} • samples #${d.start}–#${d.end - 1} · ${fmtInt(d.total_rows_in_year)} rows in year` : "loading…"}
          </div>
        </div>
        <div className="flex flex-wrap items-start gap-x-8 gap-y-4 px-5 py-4">
          <label className="flex flex-col gap-1.5">
            <span className="label">Year</span>
            <select className="input" value={year} onChange={(e) => changeYear(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <ThresholdInput
            label="CO threshold"
            value={coText}
            onChange={setCoText}
            placeholder={d ? fmtNum(d.thresholds.co_default_p95, 2) : "p95"}
            invalid={coInvalid}
            defaultValue={d?.thresholds.co_default_p95 ?? null}
            onReset={() => setCoText("")}
          />
          <ThresholdInput
            label="NOX threshold"
            value={noxText}
            onChange={setNoxText}
            placeholder={d ? fmtNum(d.thresholds.nox_default_p95, 1) : "p95"}
            invalid={noxInvalid}
            defaultValue={d?.thresholds.nox_default_p95 ?? null}
            onReset={() => setNoxText("")}
          />
        </div>
        <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
          {d?.thresholds.label ?? "screening threshold = p95 of this year, not a permit limit"}. Excursion = at least 3 consecutive samples above the threshold.
        </div>
      </div>

      {q.error ? <ErrorBanner className="mb-5" title="Could not load emissions screening" error={q.error} onRetry={q.reload} /> : null}

      <div className="mb-6 grid grid-cols-4 gap-4">
        <KpiCard
          label="Hours above threshold"
          value={d ? fmtInt(d.kpis.hours_above_any) : "—"}
          caption={d ? `CO ${fmtInt(d.kpis.hours_above_co)} · NOX ${fmtInt(d.kpis.hours_above_nox)} (hourly samples; rows not guaranteed contiguous)` : undefined}
          icon={<Wind size={18} />}
          loading={q.loading && !d}
          tone="amber"
        />
        <KpiCard
          label="Excursions"
          value={d ? fmtInt(d.kpis.excursions_total) : "—"}
          caption={d ? `CO ${d.kpis.excursions_co} · NOX ${d.kpis.excursions_nox} · longest ${d.kpis.longest_excursion_samples} samples` : undefined}
          loading={q.loading && !d}
          tone="amber"
        />
        <KpiCard
          label="Corr. CO vs TEY"
          value={d ? fmtNum(d.kpis.corr_co_tey.spearman, 2) : "—"}
          caption={d ? corrText(d.kpis.corr_co_tey) : undefined}
          loading={q.loading && !d}
        />
        <KpiCard
          label="Corr. CO vs AT"
          value={d ? fmtNum(d.kpis.corr_co_at.spearman, 2) : "—"}
          caption={d ? corrText(d.kpis.corr_co_at) : undefined}
          loading={q.loading && !d}
        />
      </div>

      {q.loading && !d ? (
        <div className="mb-6 grid gap-4">
          <ChartSkeleton />
          <ChartSkeleton />
        </div>
      ) : null}

      {d ? (
        <>
          <div className="mb-6 grid gap-4">
            <ThresholdSeriesChart
              title="CO — measured series"
              unit={d.co_unit}
              year={d.source_year}
              rows={coRows}
              color={COLORS.co}
              threshold={d.thresholds.co}
              excursions={coEx}
              badges={<ScreeningBadge title={customCo ? "User-set screening threshold" : d.thresholds.label} />}
            />
            <ThresholdSeriesChart
              title="NOX — measured series"
              unit={d.nox_unit}
              year={d.source_year}
              rows={noxRows}
              color={COLORS.nox}
              threshold={d.thresholds.nox}
              excursions={noxEx}
              badges={<ScreeningBadge title={customNox ? "User-set screening threshold" : d.thresholds.label} />}
            />
            {d.downsample_factor > 1 ? (
              <InfoBanner>
                Charts show a {d.series_note}; KPIs and the excursion table use every sample.
              </InfoBanner>
            ) : null}
          </div>

          <div className="mb-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-ink-50">Regime context — emissions vs load and TIT</h2>
                <div className="text-sm text-ink-300">{d.profile_basis}. TEY is MWh as published (load proxy).</div>
              </div>
              <div className="inline-flex overflow-hidden rounded-lg border border-ink-600" role="group" aria-label="Profile x axis">
                {(["tey", "tit"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setProfileX(k)}
                    aria-pressed={profileX === k}
                    className={`h-9 px-4 text-sm font-semibold ${profileX === k ? "bg-blue-600 text-white" : "bg-white text-ink-200 hover:bg-ink-800"}`}
                  >
                    vs {k.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <InfoBanner className="mb-4">{loadStatement(d)}</InfoBanner>
            <div className="grid grid-cols-2 gap-4">
              <ProfileChart
                title={`CO by ${profileX.toUpperCase()} decile`}
                bins={profileX === "tey" ? d.profile_tey : d.profile_tit}
                x={profileX}
                pollutant="co"
                unit={d.co_unit}
                color={COLORS.co}
                footer={`n per bin ≈ ${fmtInt(Math.round(d.kpis.rows_analyzed / Math.max(1, d.profile_tey.length)))}; CO vs TEY ${corrText(d.kpis.corr_co_tey)}`}
              />
              <ProfileChart
                title={`NOX by ${profileX.toUpperCase()} decile`}
                bins={profileX === "tey" ? d.profile_tey : d.profile_tit}
                x={profileX}
                pollutant="nox"
                unit={d.nox_unit}
                color={COLORS.nox}
                footer={`NOX vs AT ${corrText(d.kpis.corr_nox_at)}; NOX vs TEY ${corrText(d.kpis.corr_nox_tey)}`}
              />
            </div>
          </div>

          <div className="panel mb-6">
            <div className="panel-header">
              <div>
                <div className="panel-title">Excursions ({fmtInt(d.excursions.length)})</div>
                <div className="mt-0.5 text-sm text-ink-300">
                  Context column is a <strong>heuristic</strong> from simple rules on concurrent TEY / TIT / AT; it is not a root-cause finding.
                </div>
              </div>
              <ScreeningBadge />
            </div>
            {d.excursions.length === 0 ? (
              <div className="px-5 py-8 text-center text-base text-ink-400">No excursions of at least 3 consecutive samples at these thresholds.</div>
            ) : (
              <div className="max-h-[560px] overflow-auto">
                <table className="table-base">
                  <thead className="sticky top-0 bg-ink-850">
                    <tr>
                      <th>Pollutant</th>
                      <th>Start → end (sample #)</th>
                      <th className="text-right">Samples</th>
                      <th className="text-right">Peak (mg/m³)</th>
                      <th className="text-right">Peak / thr.</th>
                      <th className="text-right">TEY</th>
                      <th className="text-right">TIT</th>
                      <th className="text-right">AT</th>
                      <th>Heuristic context</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.excursions.map((e) => (
                      <tr key={e.excursion_id}>
                        <td>
                          <span className="font-semibold" style={{ color: e.pollutant === "CO" ? COLORS.co : COLORS.nox }}>
                            {e.pollutant}
                          </span>
                        </td>
                        <td className="font-mono">
                          #{e.start_index} → #{e.end_index}
                        </td>
                        <td className="text-right font-mono tabular-nums">{e.n_samples}</td>
                        <td className="text-right font-mono tabular-nums">
                          {fmtNum(e.peak_value, 2)} <span className="text-ink-400">@#{e.peak_index}</span>
                        </td>
                        <td className="text-right font-mono tabular-nums">{fmtNum(e.peak_ratio, 2)}×</td>
                        <td className="text-right font-mono tabular-nums">{fmtNum(e.tey_mean, 1)}</td>
                        <td className="text-right font-mono tabular-nums">
                          {fmtNum(e.tit_mean, 0)}
                          {e.tit_change !== null ? <span className="ml-1 text-ink-400">({e.tit_change > 0 ? "+" : ""}{fmtNum(e.tit_change, 0)})</span> : null}
                        </td>
                        <td className="text-right font-mono tabular-nums">{fmtNum(e.at_mean, 1)}</td>
                        <td className="text-sm">{e.context}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">
              {d.excursions_truncated ? "List truncated to the first 500 excursions. " : ""}
              TIT value in brackets = change from 3 samples before the excursion start to its end (°C). Rules: {d.context_rules.join(" · ")}
            </div>
          </div>

          <div className="px-1 pb-8 text-sm text-ink-400">{d.disclaimer}</div>
        </>
      ) : null}
    </div>
  );
}
