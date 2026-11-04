import { Activity, ChevronDown, ChevronRight, Database, FlaskConical, Gauge, Layers, Play, Search, Sigma } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createInvestigation,
  errorMessage,
  getHealth,
  getModelEvaluation,
  getSeries,
  isApiError,
  listDatasets,
  listInvestigations,
  listScenarios,
} from "../api/client";
import { MEASUREMENTS, MEASUREMENT_KEYS } from "../api/types";
import type { ScenarioInfo, SeriesResponse } from "../api/types";
import { ChartSkeleton, EmptyDataset, ErrorBanner, InfoBanner, Spinner, WarnBanner } from "../components/Feedback";
import { KpiCard } from "../components/KpiCard";
import { PageHeader } from "../components/Layout";
import { PlantAnimation } from "../components/PlantAnimation";
import { PlantSchematic } from "../components/PlantSchematic";
import { SERIES_COLORS, SeriesChart } from "../components/SeriesChart";
import type { ChartRow } from "../components/SeriesChart";
import { SourceBadge } from "../components/SourceBadge";
import { useAsync } from "../hooks/useAsync";
import { fmtInt, fmtNum, sampleLabel } from "../lib/format";

const DEFAULT_LENGTH = 120;

function toRows(s: SeriesResponse | null, withExpected: boolean): ChartRow[] {
  if (!s) return [];
  return s.points.map((p) => {
    const row: ChartRow = { row_index: p.row_index, value: p.value };
    if (withExpected) row.expected = p.expected;
    return row;
  });
}

export function OverviewPage() {
  const navigate = useNavigate();
  const health = useAsync((s) => getHealth(s), []);
  const datasets = useAsync((s) => listDatasets(s), []);
  const evaluation = useAsync((s) => getModelEvaluation(s), []);
  const investigations = useAsync((s) => listInvestigations(s), []);
  const scenarios = useAsync((s) => listScenarios(s), []);

  const dataset = useMemo(() => {
    const list = datasets.data ?? [];
    return list.find((d) => d.dataset_id === "ds_uci_551") ?? list[0] ?? null;
  }, [datasets.data]);

  const [scenarioId, setScenarioId] = useState<string>("S01_NORMAL");
  const [year, setYear] = useState<number>(2014);
  const [start, setStart] = useState<number>(1200);
  const [length, setLength] = useState<number>(DEFAULT_LENGTH);
  const [useMeta, setUseMeta] = useState(true);
  const [running, setRunning] = useState(false);
  const [walkthroughOpen, setWalkthroughOpen] = useState(false);
  const [runError, setRunError] = useState<unknown>(null);
  const [elapsed, setElapsed] = useState(0);

  const scenario: ScenarioInfo | null = useMemo(
    () => (scenarios.data ?? []).find((s) => s.scenario_id === scenarioId) ?? null,
    [scenarios.data, scenarioId],
  );

  // adopt scenario defaults when the scenario changes
  function selectScenario(id: string) {
    setScenarioId(id);
    const s = (scenarios.data ?? []).find((x) => x.scenario_id === id);
    if (s) {
      setYear(s.default_year);
      setStart(s.default_start);
      setLength(Math.max(1, s.default_end - s.default_start));
    }
  }

  useEffect(() => {
    if (!running) return;
    const t0 = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500);
    return () => window.clearInterval(id);
  }, [running]);

  const metaConfigured = health.data?.meta_configured ?? false;
  const modelReady = health.data?.model_ready ?? false;
  const effectiveUseMeta = useMeta && metaConfigured;
  const datasetId = dataset?.dataset_id ?? null;
  const safeLength = Math.max(1, Math.min(2000, length));

  const tey = useAsync(
    async (signal) =>
      datasetId ? getSeries(datasetId, { measure: "TEY", year, start, limit: safeLength, include_expected: true }, signal) : null,
    [datasetId, year, start, safeLength],
  );
  const afdp = useAsync(
    async (signal) => (datasetId ? getSeries(datasetId, { measure: "AFDP", year, start, limit: safeLength }, signal) : null),
    [datasetId, year, start, safeLength],
  );
  // latest values at window end for the schematic tags (11 tiny requests; tolerant to failures)
  const tagValues = useAsync(
    async (signal) => {
      if (!datasetId) return {};
      const endIdx = Math.max(0, start + safeLength - 1);
      const results = await Promise.allSettled(
        MEASUREMENT_KEYS.map((m) => getSeries(datasetId, { measure: m, year, start: endIdx, limit: 1 }, signal)),
      );
      const out: Record<string, number | null> = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") out[MEASUREMENT_KEYS[i]] = r.value.points[0]?.value ?? null;
      });
      return out;
    },
    [datasetId, year, start, safeLength],
  );

  const teyRows = useMemo(() => toRows(tey.data, true), [tey.data]);
  const afdpRows = useMemo(() => toRows(afdp.data, false), [afdp.data]);
  const windowEnd = start + safeLength;

  const openCount = (investigations.data ?? []).filter((i) => i.review === null && i.status !== "failed").length;
  const evalMissing = isApiError(evaluation.error) && evaluation.error.status === 404;

  async function run() {
    if (!datasetId) return;
    setRunning(true);
    setRunError(null);
    try {
      const created = await createInvestigation({
        dataset_id: datasetId,
        scenario_id: scenarioId,
        year,
        start_index: start,
        end_index: windowEnd,
        seed: scenario?.default_seed ?? null,
        use_meta: effectiveUseMeta,
      });
      navigate(`/investigations/${created.case_id}`);
    } catch (e) {
      setRunError(e);
      setRunning(false);
    }
  }

  const datasetEmpty = !datasets.loading && !datasets.error && (datasets.data?.length ?? 0) === 0;

  return (
    <div>
      <PageHeader
        title="ThermoMind — Gas Turbine Diagnostic Intelligence"
        subtitle="Evidence-first industrial diagnostics · experimental engineering decision-support prototype, not a validated diagnostic or safety system"
        right={
          <>
            <SourceBadge variant="real" label="REAL UCI TURBINE DATA · TURKEY · 2011–2015 · CC BY 4.0" />
            {scenario?.synthetic ? <SourceBadge variant="synthetic" label="SYNTHETIC SCENARIO" /> : null}
          </>
        }
      />

      {datasets.error ? <ErrorBanner className="mb-5" title="Could not load datasets" error={datasets.error} onRetry={datasets.reload} /> : null}
      {datasetEmpty ? <EmptyDataset className="mb-5" /> : null}
      {health.data && !health.data.model_ready ? (
        <WarnBanner className="mb-5">
          Baseline model not trained — expected TEY and residual evidence are unavailable. Run{" "}
          <code className="font-mono text-amber-800">make train</code> from the repository root.
        </WarnBanner>
      ) : null}

      <div className="mb-6 grid grid-cols-4 gap-4">
        <KpiCard
          label="Source rows"
          value={dataset ? fmtInt(dataset.row_count) : "—"}
          caption={dataset ? `${dataset.years.length} years · ${dataset.source}` : "no dataset loaded"}
          icon={<Database size={18} />}
          loading={datasets.loading}
        />
        <KpiCard
          label="Measurements"
          value={dataset ? dataset.columns.filter((c) => c in MEASUREMENTS).length || 11 : 11}
          caption="hourly aggregates, no row-level timestamps"
          icon={<Gauge size={18} />}
          loading={datasets.loading}
        />
        <KpiCard
          label="Holdout MAE"
          value={evaluation.data ? fmtNum(evaluation.data.holdout.mae, 2) : evalMissing ? "n/a" : "—"}
          unit={evaluation.data ? "MWh" : undefined}
          caption={evaluation.data ? `baseline model, ${evaluation.data.split.test_years.join("/")} holdout · R² ${fmtNum(evaluation.data.holdout.r2, 3)}` : evalMissing ? "model not trained" : "baseline model, 2015 holdout"}
          icon={<Sigma size={18} />}
          loading={evaluation.loading}
          tone="model"
        />
        <KpiCard
          label="Open investigations"
          value={investigations.data ? openCount : "—"}
          caption={investigations.data ? `${investigations.data.length} total · awaiting human review` : investigations.error ? "could not load" : "loading"}
          icon={<Search size={18} />}
          loading={investigations.loading}
          tone="amber"
        />
      </div>

      <PlantSchematic
        className="mb-6"
        values={tagValues.data ?? {}}
        highlight={scenario?.synthetic ? scenario.affected_measurements : []}
      />
      {tagValues.data && Object.keys(tagValues.data).length > 0 ? (
        <div className="-mt-4 mb-6 px-1 text-sm text-ink-400">
          Tag values are the real measurements at {sampleLabel(year, Math.max(0, windowEnd - 1))} (end of selected window).
        </div>
      ) : null}

      {/* collapsible plant walkthrough (external educational animation, loaded only when expanded) */}
      <div className="panel mb-6">
        <button
          type="button"
          onClick={() => setWalkthroughOpen((o) => !o)}
          className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
          aria-expanded={walkthroughOpen}
        >
          <div>
            <div className="panel-title flex items-center gap-2">
              {walkthroughOpen ? <ChevronDown size={18} className="text-ink-400" /> : <ChevronRight size={18} className="text-ink-400" />}
              Plant walkthrough — interactive combined-cycle animation
            </div>
            <div className="mt-0.5 text-sm text-ink-300">
              Generic educational combined-cycle plant (educational-animation.org, MIT licence) — not the UCI facility. Click to {walkthroughOpen ? "collapse" : "expand"}.
            </div>
          </div>
          <span className="text-sm font-semibold text-blue-700">{walkthroughOpen ? "Hide" : "Show"}</span>
        </button>
        {walkthroughOpen ? (
          <div className="border-t border-ink-700 px-5 py-4">
            <PlantAnimation />
          </div>
        ) : null}
      </div>

      {/* window + scenario controls */}
      <div className="panel mb-6">
        <div className="panel-header">
          <div className="panel-title">Analysis window & scenario</div>
          <div className="text-sm text-ink-300">
            Window {sampleLabel(year, start)} → #{windowEnd - 1} · {safeLength} hourly samples · reference = 240 preceding real samples
          </div>
        </div>
        <div className="grid grid-cols-12 gap-4 px-5 py-4">
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Year</span>
            <select className="input" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {(dataset?.years ?? [2011, 2012, 2013, 2014, 2015]).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Start index</span>
            <input
              className="input font-mono"
              type="number"
              min={0}
              step={1}
              value={start}
              onChange={(e) => setStart(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
            />
          </label>
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Length (samples)</span>
            <input
              className="input font-mono"
              type="number"
              min={1}
              max={2000}
              step={1}
              value={length}
              onChange={(e) => setLength(Math.floor(Number(e.target.value) || DEFAULT_LENGTH))}
            />
          </label>
          <label className="col-span-6 flex flex-col gap-1.5">
            <span className="label">Scenario</span>
            <select className="input" value={scenarioId} onChange={(e) => selectScenario(e.target.value)} disabled={scenarios.loading}>
              {(scenarios.data ?? [{ scenario_id: "S01_NORMAL", title: "Normal operation (real data only)", synthetic: false } as ScenarioInfo]).map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>
                  {s.synthetic ? "[SYNTHETIC] " : "[REAL] "}
                  {s.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        {scenario ? (
          <div className="border-t border-ink-700 px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              {scenario.synthetic ? (
                <SourceBadge variant="synthetic" label="SYNTHETIC SCENARIO" />
              ) : (
                <SourceBadge variant="real" label="REAL DATA ONLY" />
              )}
              {scenario.affected_measurements.length > 0 ? (
                <span className="text-sm text-ink-300">
                  affects{" "}
                  {scenario.affected_measurements.map((m) => (
                    <code key={m} className="ml-1 rounded bg-amber-50 px-1.5 py-0.5 font-mono text-amber-800">
                      {m}
                    </code>
                  ))}
                </span>
              ) : null}
            </div>
            <p className="mt-2 text-base text-ink-200">{scenario.description}</p>
            {scenario.synthetic ? (
              <p className="mt-1 text-sm text-amber-800">
                <FlaskConical size={14} className="mr-1 inline" />
                The overlay is applied to a <em>copy</em> of the real rows for this window; the charts below show the unmodified
                measurements. The investigation page shows original vs overlay.
              </p>
            ) : null}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-ink-700 px-5 py-4">
          <div className="flex flex-col gap-1">
            <label className={`flex items-center gap-2 text-base ${metaConfigured ? "text-ink-100" : "text-ink-400"}`}>
              <input
                type="checkbox"
                className="h-5 w-5 accent-blue-600"
                checked={useMeta && metaConfigured}
                disabled={!metaConfigured || running}
                onChange={(e) => setUseMeta(e.target.checked)}
              />
              Use Meta Muse Spark (live)
              <span className="font-mono text-sm text-ink-400">{health.data?.meta_model ?? "muse-spark-1.3"}</span>
            </label>
            {!metaConfigured && !health.loading ? (
              <span className="text-sm text-amber-800">
                Meta Model API key not configured on the server (MODEL_API_KEY in .env) — the investigation will run as an
                OFFLINE PREVIEW built from deterministic tools only, clearly labelled as not a Meta inference.
              </span>
            ) : null}
            {!modelReady && health.data ? (
              <span className="text-sm text-amber-800">Baseline model missing: TEY residual evidence will be unavailable.</span>
            ) : null}
          </div>
          <button type="button" className="btn-primary h-11 px-5 text-base" onClick={run} disabled={running || !datasetId}>
            {running ? <Spinner /> : <Play size={18} />}
            Run diagnostic investigation
          </button>
        </div>
        {running ? (
          <div className="border-t border-ink-700 bg-ink-900/60 px-5 py-4">
            <div className="flex items-center gap-3 text-base text-ink-100">
              <Spinner className="text-blue-700" />
              <span>
                Running deterministic analysis →{" "}
                {effectiveUseMeta
                  ? `calling ${health.data?.meta_model ?? "muse-spark-1.3"} with evidence tools…`
                  : "building offline preview from deterministic tools…"}
              </span>
              <span className="ml-auto font-mono text-sm text-ink-300">{elapsed}s elapsed</span>
            </div>
            <div className="mt-2 text-sm text-ink-400">
              <Layers size={14} className="mr-1 inline" />
              The call is synchronous and may take 30–120 s with Meta live (tool loop, validation and one bounded rewrite). You will be
              redirected to the case when it finishes.
            </div>
          </div>
        ) : null}
        {runError ? (
          <div className="border-t border-ink-700 px-5 py-4">
            <ErrorBanner title="Investigation failed to start" error={runError} />
            {isApiError(runError) && runError.status === 0 ? (
              <div className="mt-2 text-sm text-ink-400">{errorMessage(runError)}</div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* charts */}
      <div className="grid grid-cols-2 gap-4">
        {tey.loading && !tey.data ? (
          <ChartSkeleton />
        ) : tey.error ? (
          <ErrorBanner title="Could not load TEY series" error={tey.error} onRetry={tey.reload} />
        ) : (
          <SeriesChart
            title={
              <span>
                TEY — {MEASUREMENTS.TEY.name} <span className="text-ink-400">({MEASUREMENTS.TEY.unit})</span>
              </span>
            }
            unit={tey.data?.unit ?? "MWh"}
            year={year}
            data={teyRows}
            series={[
              { key: "value", name: "Measured TEY", color: SERIES_COLORS.measured },
              { key: "expected", name: "Model expected TEY", color: SERIES_COLORS.expected, dashed: true, tag: "MODEL-DERIVED" },
            ]}
            badges={
              <>
                <SourceBadge variant="real" size="sm" />
                <SourceBadge variant="model" size="sm" />
              </>
            }
            footer={
              tey.data
                ? `${tey.data.points.length} points · downsample ×${tey.data.downsample_factor} · ${tey.data.total_rows_in_year} rows in ${year} · expected from ${evaluation.data?.model_version ?? "baseline model"}${teyRows.some((r) => r.expected !== null && r.expected !== undefined) ? "" : " (expected unavailable)"}`
                : null
            }
          />
        )}
        {afdp.loading && !afdp.data ? (
          <ChartSkeleton />
        ) : afdp.error ? (
          <ErrorBanner title="Could not load AFDP series" error={afdp.error} onRetry={afdp.reload} />
        ) : (
          <SeriesChart
            title={
              <span>
                AFDP — {MEASUREMENTS.AFDP.name} <span className="text-ink-400">({MEASUREMENTS.AFDP.unit})</span>
              </span>
            }
            unit={afdp.data?.unit ?? "mbar"}
            year={year}
            data={afdpRows}
            series={[{ key: "value", name: "Measured AFDP", color: SERIES_COLORS.measured }]}
            badges={<SourceBadge variant="real" size="sm" />}
            footer={afdp.data ? `${afdp.data.points.length} points · downsample ×${afdp.data.downsample_factor} · real observations, no overlay` : null}
          />
        )}
      </div>

      <InfoBanner className="mt-6" icon={<Activity size={18} />}>
        Rows are ordered hourly aggregates from an undisclosed Turkish combined-cycle plant (UCI ML Repository #551). No verified
        fault labels exist; synthetic scenarios are illustrative overlays on copies of real rows and are labelled at every layer.
      </InfoBanner>
    </div>
  );
}
