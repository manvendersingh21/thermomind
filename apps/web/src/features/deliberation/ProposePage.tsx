import { ExternalLink, Loader2, Plus, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorBanner, PanelSkeleton, WarnBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { useAsync } from "../../hooks/useAsync";
import { getPersonas, listInvestigationsForPicker } from "../../plant/api";
import { getPersona } from "../../plant/persona";
import { AgentCards } from "./AgentCards";
import { DecisionPanel } from "./DecisionPanel";
import { ChangePanel, FindingsPanel, OutcomePanel, PanelTitle, RehearsalPanel } from "./ResultPanels";
import { Chip, humanize } from "./badges";
import { getDeliberation, getIntents, listDeliberations, proposeAction } from "./api";
import type { DeliberationSession, IntentInfo, ProposeRequest } from "./types";

const BANNER = "Advisory deliberation between software agents — the human decides; ThermoMind executes nothing";
const MEASUREMENTS = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"];
const YEARS = [2011, 2012, 2013, 2014, 2015];
const POLL_MS = 1500;

const CUSTOM_FALLBACK: IntentInfo = {
  intent_id: "custom",
  label: "Custom change",
  description: "Describe your own change and the measurement deltas you expect.",
  magnitude: null,
  subsystems: [],
  primary_measurement: null,
  observable: true,
  notes: [],
};

interface DeltaRow {
  id: number;
  measurement: string;
  delta: string;
}

const STATUS_STYLE: Record<string, string> = {
  running: "border-blue-300 bg-blue-50 text-blue-800",
  completed: "border-green-300 bg-green-50 text-green-800",
  needs_review: "border-amber-300 bg-amber-50 text-amber-900",
  failed: "border-red-300 bg-red-50 text-red-800",
};

export default function ProposePage() {
  const [params, setParams] = useSearchParams();
  const idParam = params.get("id");
  const caseParam = params.get("case_id");

  // ---- reference data
  const intents = useAsync((s) => getIntents(s), []);
  const cases = useAsync((s) => listInvestigationsForPicker(s), []);
  const personas = useAsync((s) => getPersonas(s), []);
  const [recentTick, setRecentTick] = useState(0);
  const recent = useAsync((s) => listDeliberations({ limit: 8 }, s), [recentTick]);

  const intentList = useMemo(() => {
    const l = intents.data ?? [];
    return l.some((i) => i.intent_id === "custom") ? l : intents.data ? [...l, CUSTOM_FALLBACK] : l;
  }, [intents.data]);

  // ---- form state
  const [sourceMode, setSourceMode] = useState<"case" | "manual">("case");
  const [caseId, setCaseId] = useState<string>(caseParam ?? "");
  const [year, setYear] = useState(2014);
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState("144");
  const [intentId, setIntentId] = useState<string>("");
  const [magnitude, setMagnitude] = useState<number>(0);
  const [persona, setPersona] = useState<string>(() => getPersona());
  const [customText, setCustomText] = useState("");
  const [rows, setRows] = useState<DeltaRow[]>([{ id: 1, measurement: "AT", delta: "" }]);
  const rowId = useRef(2);
  const [formError, setFormError] = useState<string | null>(null);

  // ---- session state
  const [session, setSession] = useState<DeliberationSession | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [pollError, setPollError] = useState<unknown>(null);
  const [pollKey, setPollKey] = useState(0);
  const [loadingId, setLoadingId] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  sessionIdRef.current = session?.deliberation_id ?? null;

  const intent = intentList.find((i) => i.intent_id === intentId) ?? null;
  const spec = intent?.magnitude ?? null;
  const isCustom = intentId === "custom";

  // default intent once loaded
  useEffect(() => {
    if (!intentId && intentList.length) {
      const first = intentList.find((i) => i.intent_id !== "custom") ?? intentList[0];
      setIntentId(first.intent_id);
      if (first.magnitude) setMagnitude(first.magnitude.default);
    }
  }, [intentList, intentId]);

  // default case: no preselect unless provided; fall back to manual when there are no cases
  useEffect(() => {
    if (cases.data && cases.data.length === 0 && sourceMode === "case") setSourceMode("manual");
  }, [cases.data, sourceMode]);

  function pickIntent(id: string) {
    setIntentId(id);
    const m = intentList.find((i) => i.intent_id === id)?.magnitude;
    if (m) setMagnitude(m.default);
  }

  const personaList = personas.data?.personas ?? [];
  const personaLabel = useCallback(
    (id: string) => {
      const p = personaList.find((x) => x.persona_id === id);
      return p ? `${p.name} (${p.role})` : humanize(id);
    },
    [personaList],
  );

  // ---- load a session from ?id=
  useEffect(() => {
    if (!idParam || idParam === sessionIdRef.current) return;
    const ctl = new AbortController();
    setLoadingId(true);
    setLoadError(null);
    getDeliberation(idParam, ctl.signal)
      .then((s) => {
        setSession(s);
        setPollError(null);
      })
      .catch((e: unknown) => {
        if (!ctl.signal.aborted) setLoadError(e);
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoadingId(false);
      });
    return () => ctl.abort();
  }, [idParam]);

  // ---- poll while running
  const runningId = session?.status === "running" ? session.deliberation_id : null;
  useEffect(() => {
    if (!runningId) return;
    let cancelled = false;
    let failures = 0;
    let timer: number | undefined;
    const ctl = new AbortController();
    const tick = async () => {
      try {
        const s = await getDeliberation(runningId, ctl.signal);
        if (cancelled) return;
        failures = 0;
        setPollError(null);
        setSession(s);
        if (s.status === "running") timer = window.setTimeout(tick, POLL_MS);
        else setRecentTick((t) => t + 1);
      } catch (e) {
        if (cancelled) return;
        failures += 1;
        if (failures >= 4) setPollError(e);
        else timer = window.setTimeout(tick, POLL_MS * 2);
      }
    };
    timer = window.setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      ctl.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runningId, pollKey]);

  // ---- submit
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitError(null);
    if (!intentId) return setFormError("Pick an intent first.");
    const body: ProposeRequest = { dataset_id: "ds_uci_551", intent_id: intentId, persona };

    if (sourceMode === "case") {
      if (!caseId) return setFormError("Pick a case, or switch to a manual window.");
      body.case_id = caseId;
    } else {
      const s = Number(start);
      const en = Number(end);
      if (!Number.isInteger(s) || !Number.isInteger(en) || s < 0 || en < 1 || en <= s) {
        return setFormError("Window needs integer start >= 0 and end > start (end is exclusive).");
      }
      body.year = year;
      body.start = s;
      body.end = en;
    }

    if (isCustom) {
      const text = customText.trim();
      if (text.length < 3) return setFormError("Describe the custom change (at least 3 characters).");
      const deltas: Record<string, number> = {};
      for (const r of rows) {
        if (r.delta.trim() === "") continue;
        const v = Number(r.delta);
        if (!Number.isFinite(v)) return setFormError(`Delta for ${r.measurement} is not a number.`);
        deltas[r.measurement] = v;
      }
      body.custom = { text, deltas };
    } else if (spec) {
      if (!Number.isFinite(magnitude)) return setFormError("Magnitude is not a number.");
      body.magnitude = magnitude;
    }

    setSubmitting(true);
    setLoadError(null);
    setPollError(null);
    try {
      const s = await proposeAction(body);
      setSession(s);
      setParams({ id: s.deliberation_id }, { replace: false });
      setRecentTick((t) => t + 1);
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  }

  const running = session?.status === "running";
  const doneAgents = session ? session.agents.filter((a) => a.status === "done" || a.status === "failed").length : 0;
  const banner = session?.banner || BANNER;

  return (
    <div>
      <PageHeader
        title="Propose an action"
        subtitle="Describe a change you are considering. Software agents for each subsystem, a constraints agent and an aggregator discuss it over deterministic pre-checks; you then decide."
      />

      <div role="note" className="mb-6 rounded-xl border border-blue-300 bg-blue-50 px-4 py-3 text-base font-semibold text-blue-900">
        {banner}
      </div>

      {/* ------------------------------------------------------------ inputs */}
      <form onSubmit={(e) => void submit(e)} className="panel mb-6" aria-label="Proposal inputs">
        <PanelTitle>1. What do you want to change?</PanelTitle>
        <div className="space-y-5 px-5 py-4">
          {cases.error ? <WarnBanner>Case list unavailable; use a manual window instead.</WarnBanner> : null}
          {intents.error ? <ErrorBanner error={intents.error} title="Could not load intents" onRetry={intents.reload} /> : null}

          <fieldset className="space-y-3">
            <legend className="label mb-1">Data window</legend>
            <div className="flex flex-wrap gap-4 text-base text-ink-100">
              <label className="flex items-center gap-2">
                <input type="radio" name="src" checked={sourceMode === "case"} onChange={() => setSourceMode("case")} /> From an investigation case
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="src" checked={sourceMode === "manual"} onChange={() => setSourceMode("manual")} /> Manual window
              </label>
            </div>
            {sourceMode === "case" ? (
              <label className="flex max-w-2xl flex-col gap-1.5">
                <span className="label">Case</span>
                <select className="input" value={caseId} onChange={(e) => setCaseId(e.target.value)} disabled={cases.loading}>
                  <option value="">{cases.loading ? "Loading cases..." : "Select a case"}</option>
                  {caseParam && !(cases.data ?? []).some((c) => c.case_id === caseParam) ? <option value={caseParam}>{caseParam}</option> : null}
                  {(cases.data ?? []).map((c) => (
                    <option key={c.case_id} value={c.case_id}>
                      {c.case_id} — {c.scenario.title} ({c.window.source_year}, rows {c.window.start}–{c.window.end})
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <div className="flex flex-wrap gap-3">
                <label className="flex flex-col gap-1.5">
                  <span className="label">Year</span>
                  <select className="input w-28" value={year} onChange={(e) => setYear(Number(e.target.value))}>
                    {YEARS.map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="label">Start row</span>
                  <input className="input w-32" inputMode="numeric" value={start} onChange={(e) => setStart(e.target.value)} />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="label">End row (exclusive)</span>
                  <input className="input w-32" inputMode="numeric" value={end} onChange={(e) => setEnd(e.target.value)} />
                </label>
                <p className="max-w-sm self-end pb-2 text-xs text-ink-400">
                  Row indices within the source year; the data has no row-level timestamps.
                </p>
              </div>
            )}
          </fieldset>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <label className="flex flex-col gap-1.5">
                <span className="label">Intent</span>
                <select className="input" value={intentId} onChange={(e) => pickIntent(e.target.value)} disabled={intents.loading} aria-describedby="intent-desc">
                  {intents.loading ? <option value="">Loading intents...</option> : null}
                  {intentList.map((i) => (
                    <option key={i.intent_id} value={i.intent_id}>
                      {i.label}
                    </option>
                  ))}
                </select>
              </label>
              <div id="intent-desc" className="space-y-1 text-sm text-ink-300">
                {intent ? <p>{intent.description}</p> : null}
                {intent && !intent.observable ? (
                  <p>
                    <Chip cls="border-dashed border-ink-500 bg-ink-800 text-ink-300">not observable in this data</Chip> qualitative only.
                  </p>
                ) : null}
                {intent?.notes.map((n, i) => (
                  <p key={i} className="text-ink-400">
                    {n}
                  </p>
                ))}
              </div>
            </div>

            {spec ? (
              <div className="space-y-1.5">
                <span className="label">{spec.label}</span>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    aria-label={`${spec.label} slider`}
                    className="min-w-0 flex-1"
                    min={spec.min}
                    max={spec.max}
                    step={spec.step}
                    value={magnitude}
                    onChange={(e) => setMagnitude(Number(e.target.value))}
                  />
                  <input
                    type="number"
                    aria-label={`${spec.label} value`}
                    className="input w-28"
                    min={spec.min}
                    max={spec.max}
                    step={spec.step}
                    value={Number.isFinite(magnitude) ? magnitude : ""}
                    onChange={(e) => setMagnitude(e.target.value === "" ? NaN : Number(e.target.value))}
                  />
                  <span className="font-mono text-sm text-ink-200">{spec.unit}</span>
                </div>
                <p className="text-xs text-ink-400">
                  Range {spec.min} to {spec.max} {spec.unit}, step {spec.step}; default {spec.default}.
                </p>
              </div>
            ) : null}
          </div>

          {isCustom ? (
            <div className="space-y-3 rounded-lg border border-ink-700 bg-white p-4">
              <label className="flex flex-col gap-1.5">
                <span className="label">Describe the change</span>
                <textarea
                  className="input h-auto py-2"
                  rows={2}
                  minLength={3}
                  maxLength={500}
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  placeholder="e.g. Bypass the inlet air filter pre-stage during the dry season"
                />
              </label>
              <div>
                <div className="label mb-1">Expected measurement deltas (optional)</div>
                <ul className="space-y-2">
                  {rows.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center gap-2">
                      <select
                        aria-label="Measurement"
                        className="input w-28"
                        value={r.measurement}
                        onChange={(e) => setRows((rs) => rs.map((x) => (x.id === r.id ? { ...x, measurement: e.target.value } : x)))}
                      >
                        {MEASUREMENTS.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                      <input
                        type="number"
                        step="any"
                        aria-label={`Delta for ${r.measurement}`}
                        className="input w-32"
                        placeholder="delta"
                        value={r.delta}
                        onChange={(e) => setRows((rs) => rs.map((x) => (x.id === r.id ? { ...x, delta: e.target.value } : x)))}
                      />
                      <button
                        type="button"
                        className="btn-secondary h-10 px-3"
                        aria-label="Remove row"
                        onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                      >
                        <Trash2 size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="btn-secondary mt-2 h-9 px-3 text-sm"
                  onClick={() => setRows((rs) => [...rs, { id: rowId.current++, measurement: "AT", delta: "" }])}
                >
                  <Plus size={14} /> Add measurement
                </button>
                <p className="mt-1 text-xs text-ink-400">Deltas are your stated intent (operator intent), not measurements; units are those of the measurement.</p>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-end gap-4">
            <label className="flex min-w-[16rem] flex-col gap-1.5">
              <span className="label">Asking as</span>
              <select className="input" value={persona} onChange={(e) => setPersona(e.target.value)}>
                {personaList.map((p) => (
                  <option key={p.persona_id} value={p.persona_id}>
                    {p.name} ({p.role})
                  </option>
                ))}
                {!personaList.some((p) => p.persona_id === persona) ? <option value={persona}>{persona}</option> : null}
              </select>
            </label>
            <button type="submit" className="btn-primary" disabled={submitting || running || !intentId}>
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />} Ask the agents
            </button>
          </div>
          {formError ? (
            <p role="alert" className="text-sm font-medium text-red-800">
              {formError}
            </p>
          ) : null}
          {submitError ? <ErrorBanner error={submitError} title="Could not start the deliberation" /> : null}
        </div>
      </form>

      {loadingId && !session ? <PanelSkeleton lines={5} /> : null}
      {loadError ? <ErrorBanner error={loadError} title="Could not load deliberation" className="mb-6" /> : null}

      {session ? (
        <div className="space-y-6">
          {/* ---------------------------------------------------------- header strip */}
          <section className="panel px-5 py-4" aria-label="Deliberation summary">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-ink-300">{session.deliberation_id}</span>
              <Chip cls={STATUS_STYLE[session.status] ?? ""}>{humanize(session.status)}</Chip>
              <Chip cls={session.mode === "meta_live" ? "border-blue-200 bg-blue-50 text-blue-800" : "border-amber-300 bg-amber-50 text-amber-900"}>
                {session.mode_label}
              </Chip>
              {session.meta_model ? <Chip cls="border-blue-200 bg-white font-mono text-blue-800">{session.meta_model}</Chip> : null}
              {session.wall_ms !== null ? <Chip>wall {(session.wall_ms / 1000).toFixed(1)} s</Chip> : null}
              {session.case_id ? (
                <Link to={`/investigations/${encodeURIComponent(session.case_id)}`} className="ml-auto inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline">
                  Open case {session.case_id} <ExternalLink size={14} />
                </Link>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-ink-400">
              Asked by {personaLabel(session.persona)} at {session.created_at_utc}
            </p>
            {session.error ? <p className="mt-2 text-sm font-medium text-red-800">Error: {session.error}</p> : null}
            {session.validation_errors.length > 0 ? (
              <details className="mt-2 text-sm">
                <summary className="cursor-pointer text-amber-900">Validation errors ({session.validation_errors.length})</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-200">
                  {session.validation_errors.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>

          {/* ---------------------------------------------------------- progress */}
          <div aria-live="polite" role="status" className={running ? "flex items-center gap-2 text-base font-medium text-blue-800" : "sr-only"}>
            {running ? (
              <>
                <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                Agents are deliberating: {doneAgents} of {session.agents.length || "?"} finished
              </>
            ) : (
              `Deliberation ${humanize(session.status)}`
            )}
          </div>
          {pollError ? <ErrorBanner error={pollError} title="Lost contact while following progress" onRetry={() => {
            setPollError(null);
            setPollKey((k) => k + 1);
          }} /> : null}

          <ChangePanel change={session.change} />
          <FindingsPanel findings={session.constraint_findings} />

          <AgentCards
            agents={session.agents}
            heading={<h2 className="mb-2 text-lg font-bold text-ink-50">Agents</h2>}
          />

          {session.outcome ? <OutcomePanel outcome={session.outcome} personaLabel={personaLabel} /> : null}
          {session.rehearsal ? <RehearsalPanel r={session.rehearsal} /> : null}

          <DecisionPanel
            session={session}
            personas={personaList}
            persona={persona}
            onPersona={setPersona}
            onUpdated={(s) => {
              setSession(s);
              setRecentTick((t) => t + 1);
            }}
          />
          <p className="text-xs text-ink-400">{session.disclaimer}</p>
        </div>
      ) : null}

      {/* ------------------------------------------------------------ recent */}
      {recent.data && recent.data.length > 0 ? (
        <section className="panel mt-6" aria-label="Recent deliberations">
          <PanelTitle>Recent deliberations</PanelTitle>
          <ul className="divide-y divide-ink-700/60 px-5">
            {recent.data.map((d) => (
              <li key={d.deliberation_id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <Link to={`/propose?id=${encodeURIComponent(d.deliberation_id)}`} className="font-mono font-semibold text-blue-700 hover:underline">
                  {d.deliberation_id}
                </Link>
                <Chip cls={STATUS_STYLE[d.status] ?? ""}>{humanize(d.status)}</Chip>
                <span className="text-ink-200">{d.change.label}</span>
                {d.outcome ? <span className="text-ink-400">· {humanize(d.outcome.recommendation)}</span> : null}
                <span className="ml-auto font-mono text-xs text-ink-400">{d.created_at_utc}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
