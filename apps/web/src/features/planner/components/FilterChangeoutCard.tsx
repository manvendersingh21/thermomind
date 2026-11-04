import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Wind } from "lucide-react";
import { ErrorBanner, Spinner } from "../../../components/Feedback";
import { SourceBadge } from "../../../components/SourceBadge";
import { fmtInt, fmtNum } from "../../../lib/format";
import { runFilterChangeout } from "../api";
import type { FilterChangeoutResult, FilterInputs } from "../types";
import { AssumptionInput } from "./AssumptionInput";
import { PLANNER_COLORS, PlannerChart } from "./PlannerChart";
import type { PlannerRow } from "./PlannerChart";
import { AssumptionsEcho, Computation, Kpi, StatusBox, parseNumbers } from "./ResultParts";

type Form = Record<keyof FilterInputs, string>;

const toForm = (d: FilterInputs): Form => ({
  rolling_window_samples: String(d.rolling_window_samples),
  energy_price_per_mwh: String(d.energy_price_per_mwh),
  afdp_limit_mbar: String(d.afdp_limit_mbar),
  trend_window_samples: String(d.trend_window_samples),
  filter_change_cost: String(d.filter_change_cost),
  filter_outage_hours: String(d.filter_outage_hours),
});

export function FilterChangeoutCard({
  datasetId,
  year,
  defaults,
  trainingRange,
}: {
  datasetId: string;
  year: number;
  defaults: FilterInputs;
  trainingRange: number[] | null;
}) {
  const [form, setForm] = useState<Form>(() => toForm(defaults));
  const [result, setResult] = useState<FilterChangeoutResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef(form);
  formRef.current = form;

  const run = useCallback(async () => {
    const parsed = parseNumbers<FilterInputs>(formRef.current);
    if (!parsed.ok) {
      setError(new Error(`"${parsed.key}" must be a number`));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await runFilterChangeout({ dataset_id: datasetId, year, ...parsed.value }));
    } catch (e) {
      setError(e);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, [datasetId, year]);

  useEffect(() => {
    void run();
  }, [run]);

  const set = (k: keyof FilterInputs) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const rows = useMemo<PlannerRow[]>(() => {
    if (!result) return [];
    const base: PlannerRow[] = result.series.map((p) => ({
      row_index: p.row_index,
      afdp_rolling_mbar: p.afdp_rolling_mbar,
      trend_mbar: p.trend_mbar,
      projection_mbar: null,
    }));
    const proj: PlannerRow[] = result.projection.map((p) => ({
      row_index: p.row_index,
      afdp_rolling_mbar: null,
      trend_mbar: null,
      projection_mbar: p.trend_mbar,
    }));
    return [...base, ...proj].sort((a, b) => a.row_index - b.row_index);
  }, [result]);

  const ok = result && result.status !== "insufficient data";
  const rangeText = trainingRange ? `${fmtNum(trainingRange[0], 2)}–${fmtNum(trainingRange[1], 2)} mbar` : "unknown";

  return (
    <section className="panel flex flex-col">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title flex items-center gap-2">
            <Wind size={18} className="text-blue-600" /> Inlet filter change-out — ΔP trend &amp; break-even
          </div>
          <div className="mt-0.5 text-sm text-ink-300">
            Rolling AFDP trend projected to your limit; output penalty from a statistical association in the training years.
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <SourceBadge variant="real" size="sm" />
          <SourceBadge variant="model" size="sm" label="STATISTICAL PROXY" />
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
        >
          <AssumptionInput
            id="f-limit"
            label="AFDP change-out limit"
            unit="mbar"
            value={form.afdp_limit_mbar}
            onChange={set("afdp_limit_mbar")}
            step={0.1}
            min={0}
            hint={`training range ${rangeText}`}
          />
          <AssumptionInput id="f-price" label="Energy price" unit="per MWh" value={form.energy_price_per_mwh} onChange={set("energy_price_per_mwh")} step={1} min={0} />
          <AssumptionInput id="f-cost" label="Filter change cost" unit="currency" value={form.filter_change_cost} onChange={set("filter_change_cost")} step={500} min={0} />
          <AssumptionInput id="f-outage" label="Change-out outage" unit="hours" value={form.filter_outage_hours} onChange={set("filter_outage_hours")} step={1} min={0} />
          <AssumptionInput
            id="f-trend"
            label="Trend window"
            unit="hourly samples"
            value={form.trend_window_samples}
            onChange={set("trend_window_samples")}
            step={24}
            min={48}
            hint="trailing samples used for the straight-line fit"
          />
          <AssumptionInput
            id="f-win"
            label="Rolling-median window"
            unit="hourly samples"
            value={form.rolling_window_samples}
            onChange={set("rolling_window_samples")}
            step={24}
            min={24}
          />
          <div className="flex items-end gap-2 sm:col-span-2">
            <button type="submit" className="btn-primary h-10 px-4" disabled={busy}>
              {busy ? <Spinner /> : null} Compute
            </button>
            <button type="button" className="btn-secondary h-10 px-3 text-sm" onClick={() => setForm(toForm(defaults))} disabled={busy}>
              Reset defaults
            </button>
          </div>
        </form>

        {error ? <ErrorBanner title="Filter planner failed" error={error} /> : null}

        {result ? (
          <>
            <StatusBox status={result.status} reasons={result.status_reasons} />
            {ok ? (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <Kpi
                    label="Rolling AFDP now"
                    value={fmtNum(result.current_afdp_rolling_mbar, 2)}
                    unit="mbar"
                    caption={`clean level ${fmtNum(result.clean_afdp_mbar, 2)} mbar (p5)`}
                  />
                  <Kpi
                    label="Trend"
                    value={fmtNum(result.trend_slope_mbar_per_1000_samples, 3)}
                    unit="mbar / 1000 samples"
                    caption={`last ${result.trend_window_samples} samples`}
                  />
                  <Kpi
                    tone="amber"
                    label={`Hours to ${fmtNum(result.afdp_limit_mbar, 2)} mbar`}
                    value={
                      result.limit_reached
                        ? "reached"
                        : result.samples_to_limit !== null
                          ? fmtInt(Math.round(result.samples_to_limit))
                          : "no crossing"
                    }
                    caption={result.projected_limit_index !== null ? `projected sample #${result.projected_limit_index}` : "straight-line projection"}
                  />
                  <Kpi
                    tone="model"
                    label="Associated loss rate now"
                    value={fmtNum(result.lost_output_rate_now_mwh_per_sample, 3)}
                    unit="MWh / sample"
                    caption={`≈ ${fmtNum(result.economics.loss_value_rate_now_per_hour, 1)} per hour at your price`}
                  />
                  <Kpi
                    tone="amber"
                    label="Change-out cost incl. outage"
                    value={fmtNum(result.economics.total_cost, 0)}
                    caption={`vs ${fmtNum(result.economics.cumulative_loss_value, 0)} cumulative loss value`}
                  />
                  <Kpi
                    label="Payback if rate persists"
                    value={result.payback_hours_if_rate_persists !== null ? fmtInt(Math.round(result.payback_hours_if_rate_persists)) : "—"}
                    unit={result.payback_hours_if_rate_persists !== null ? "h" : undefined}
                    caption={result.break_even_index !== null ? `break-even at #${result.break_even_index}` : `break-even not reached in ${year}`}
                  />
                </div>

                <PlannerChart
                  title="Inlet filter ΔP (AFDP) — rolling median, trend and projection"
                  subtitle={`trailing ${result.rolling_window_samples}-sample median; dashed = straight-line fit / projection (not data)`}
                  unit="mbar"
                  year={year}
                  data={rows}
                  lastRealIndex={result.current_index}
                  series={[
                    { key: "afdp_rolling_mbar", name: "rolling AFDP", color: PLANNER_COLORS.real },
                    { key: "trend_mbar", name: "linear fit", color: PLANNER_COLORS.projection, dashed: true },
                    { key: "projection_mbar", name: "projection", color: PLANNER_COLORS.projection, dashed: true, connectNulls: true },
                  ]}
                  refs={[
                    { y: result.afdp_limit_mbar, label: `your limit ${fmtNum(result.afdp_limit_mbar, 2)} mbar`, color: PLANNER_COLORS.threshold },
                    ...(result.projected_limit_index !== null && !result.limit_reached
                      ? [{ x: result.projected_limit_index, label: `projected #${result.projected_limit_index}`, color: PLANNER_COLORS.threshold }]
                      : []),
                  ]}
                />
                <div className="rounded-lg border border-dashed border-green-400 bg-white px-3 py-2 text-xs text-ink-300">
                  <span className="font-semibold text-green-800">{result.proxy.statement}</span> Output penalty{" "}
                  <span className="font-mono text-ink-100">
                    {fmtNum(result.proxy.coefficient_mwh_per_sample_per_mbar, 4)} MWh/sample per mbar
                  </span>{" "}
                  (OLS partial coefficient, training years {result.proxy.training_years.join(", ") || "—"}, n = {fmtInt(result.proxy.n_rows)}); model
                  sensitivity cross-check {fmtNum(result.proxy.model_sensitivity_mwh_per_mbar, 4)}; residual-vs-AFDP slope{" "}
                  {fmtNum(result.proxy.residual_slope_mwh_per_mbar, 4)} (≈0 by construction).
                </div>
              </>
            ) : null}
            <Computation text={result.computation} />
            <AssumptionsEcho items={result.assumptions} caveats={result.caveats} />
          </>
        ) : null}
      </div>
    </section>
  );
}
