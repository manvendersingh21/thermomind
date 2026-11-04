import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Droplets } from "lucide-react";
import { ErrorBanner, Spinner } from "../../../components/Feedback";
import { SourceBadge } from "../../../components/SourceBadge";
import { fmtInt, fmtNum } from "../../../lib/format";
import { runCompressorWash } from "../api";
import type { CompressorWashResult, WashInputs } from "../types";
import { AssumptionInput } from "./AssumptionInput";
import { PLANNER_COLORS, PlannerChart } from "./PlannerChart";
import type { PlannerRow } from "./PlannerChart";
import { AssumptionsEcho, Computation, Kpi, StatusBox, parseNumbers } from "./ResultParts";

type Form = Record<keyof WashInputs, string>;

const toForm = (d: WashInputs): Form => ({
  rolling_window_samples: String(d.rolling_window_samples),
  energy_price_per_mwh: String(d.energy_price_per_mwh),
  wash_outage_hours: String(d.wash_outage_hours),
  wash_direct_cost: String(d.wash_direct_cost),
  expected_recovery_fraction: String(d.expected_recovery_fraction),
});

export function CompressorWashCard({ datasetId, year, defaults }: { datasetId: string; year: number; defaults: WashInputs }) {
  const [form, setForm] = useState<Form>(() => toForm(defaults));
  const [result, setResult] = useState<CompressorWashResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef(form);
  formRef.current = form;

  const run = useCallback(async () => {
    const parsed = parseNumbers<WashInputs>(formRef.current);
    if (!parsed.ok) {
      setError(new Error(`"${parsed.key}" must be a number`));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await runCompressorWash({ dataset_id: datasetId, year, ...parsed.value }));
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

  const set = (k: keyof WashInputs) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const rows = useMemo<PlannerRow[]>(
    () =>
      (result?.series ?? []).map((p) => ({
        row_index: p.row_index,
        rolling_residual_mwh: p.rolling_residual_mwh,
        cumulative_loss_mwh: p.cumulative_loss_mwh,
      })),
    [result],
  );

  const assumption = (k: string) => {
    const a = result?.assumptions.find((x) => x.key === k);
    return typeof a?.value === "number" ? a.value : null;
  };
  const price = assumption("energy_price_per_mwh");
  const rec = assumption("expected_recovery_fraction");
  const cost = result?.economics.total_cost ?? null;
  const thresholdMwh = cost !== null && price && rec ? cost / (price * rec) : null;
  const ok = result && result.status !== "insufficient data";

  return (
    <section className="panel flex flex-col">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title flex items-center gap-2">
            <Droplets size={18} className="text-blue-600" /> Compressor fouling — offline water-wash break-even
          </div>
          <div className="mt-0.5 text-sm text-ink-300">
            Rolling median of observed − expected TEY vs the year's best (p95) level; cumulative lost output vs wash cost.
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <SourceBadge variant="real" size="sm" />
          <SourceBadge variant="model" size="sm" />
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
          <AssumptionInput id="w-price" label="Energy price" unit="per MWh" value={form.energy_price_per_mwh} onChange={set("energy_price_per_mwh")} step={1} min={0} />
          <AssumptionInput id="w-outage" label="Wash outage" unit="hours" value={form.wash_outage_hours} onChange={set("wash_outage_hours")} step={1} min={0} />
          <AssumptionInput id="w-cost" label="Wash direct cost" unit="currency" value={form.wash_direct_cost} onChange={set("wash_direct_cost")} step={500} min={0} />
          <AssumptionInput
            id="w-rec"
            label="Expected recovery"
            unit="fraction (0–1]"
            value={form.expected_recovery_fraction}
            onChange={set("expected_recovery_fraction")}
            step={0.05}
            min={0}
            max={1}
          />
          <AssumptionInput
            id="w-win"
            label="Rolling-median window"
            unit="hourly samples"
            value={form.rolling_window_samples}
            onChange={set("rolling_window_samples")}
            step={24}
            min={24}
            hint="168 ≈ 7 days of hourly samples"
          />
          <div className="flex items-end gap-2">
            <button type="submit" className="btn-primary h-10 px-4" disabled={busy}>
              {busy ? <Spinner /> : null} Compute
            </button>
            <button type="button" className="btn-secondary h-10 px-3 text-sm" onClick={() => setForm(toForm(defaults))} disabled={busy}>
              Reset defaults
            </button>
          </div>
        </form>

        {error ? <ErrorBanner title="Wash planner failed" error={error} /> : null}

        {result ? (
          <>
            <StatusBox status={result.status} reasons={result.status_reasons} />
            {ok ? (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <Kpi
                    tone="model"
                    label="Lost-output rate now"
                    value={fmtNum(result.lost_output_rate_now_mwh_per_sample, 3)}
                    unit="MWh / hourly sample"
                    caption={`≈ ${fmtNum(result.economics.loss_value_rate_now_per_hour, 0)} per hour at your price`}
                  />
                  <Kpi
                    tone="model"
                    label="Cumulative lost output"
                    value={fmtNum(result.cumulative_lost_output_mwh, 0)}
                    unit="MWh"
                    caption={`since sample #${result.best_index ?? "—"} (best point)`}
                  />
                  <Kpi
                    tone="amber"
                    label="Wash cost incl. outage"
                    value={fmtNum(result.economics.total_cost, 0)}
                    caption={`${fmtNum(result.economics.outage_lost_output_mwh, 0)} MWh not generated during outage`}
                  />
                  <Kpi
                    tone="amber"
                    label="Recoverable value"
                    value={fmtNum(result.economics.recoverable_value, 0)}
                    caption="recovery × cumulative loss × price"
                  />
                  <Kpi
                    label="Break-even"
                    value={result.break_even_index !== null ? `#${result.break_even_index}` : "not reached"}
                    caption={result.break_even_index !== null ? `${year} sample index` : `in ${year}`}
                  />
                  <Kpi
                    label="Payback if rate persists"
                    value={result.payback_hours_if_rate_persists !== null ? fmtInt(Math.round(result.payback_hours_if_rate_persists)) : "—"}
                    unit={result.payback_hours_if_rate_persists !== null ? "h" : undefined}
                    caption="hypothetical, straight-line"
                  />
                </div>

                <PlannerChart
                  title="Rolling TEY residual (observed − expected)"
                  subtitle={`trailing ${result.rolling_window_samples}-sample median · model ${result.model_version ?? "—"}`}
                  unit="MWh"
                  year={year}
                  data={rows}
                  series={[{ key: "rolling_residual_mwh", name: "rolling residual", color: PLANNER_COLORS.model }]}
                  refs={[
                    ...(result.best_rolling_residual_mwh !== null
                      ? [{ y: result.best_rolling_residual_mwh, label: `best (p95) ${fmtNum(result.best_rolling_residual_mwh, 2)}`, color: PLANNER_COLORS.marker }]
                      : []),
                    ...(result.best_index !== null ? [{ x: result.best_index, label: `best point #${result.best_index}`, color: PLANNER_COLORS.marker }] : []),
                  ]}
                />
                <PlannerChart
                  title="Cumulative lost output since the best point"
                  subtitle="Σ max(0, best − rolling residual) × 1 h"
                  unit="MWh"
                  year={year}
                  data={rows}
                  series={[{ key: "cumulative_loss_mwh", name: "cumulative lost output", color: PLANNER_COLORS.model }]}
                  refs={[
                    ...(thresholdMwh !== null
                      ? [{ y: thresholdMwh, label: `break-even ${fmtNum(thresholdMwh, 0)} MWh (cost ÷ (price × recovery))`, color: PLANNER_COLORS.threshold }]
                      : []),
                    ...(result.break_even_index !== null
                      ? [{ x: result.break_even_index, label: `break-even #${result.break_even_index}`, color: PLANNER_COLORS.threshold }]
                      : []),
                  ]}
                />
                <div className="text-xs text-ink-400">
                  CDP context ({result.cdp.unit}): rolling {fmtNum(result.cdp.start_rolling, 2)} → {fmtNum(result.cdp.end_rolling, 2)}, trend{" "}
                  {fmtNum(result.cdp.slope_per_1000_samples, 3)} per 1000 samples. {result.cdp.note} {result.energy_unit_note}
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
