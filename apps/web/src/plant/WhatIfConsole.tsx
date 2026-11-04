import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errorMessage, getMeasurements, getSensitivity, getWhatIf, startWhatIf } from "./api";
import type {
  AgentRun,
  Confidence,
  Direction,
  EffectElsewhere,
  HowItWorks,
  NextStep,
  MeasurementInfo,
  Sensitivity,
  SubsystemAssessment,
  WhatIfSession,
} from "./types";
import { ASSOCIATION_LABEL, HOW_IT_WORKS_SOURCE, NEXT_STEPS_NOTE, WHATIF_LABEL } from "./types";
import "./plant.css";

const POLL_MS = 1500;

function fmt(v: number | null | undefined, d = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(d);
}
function fmtSigned(v: number | null | undefined, d = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(d)}`;
}
function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

const DIR_LABEL: Record<Direction, string> = {
  increase: "increase ▲",
  decrease: "decrease ▼",
  no_clear_change: "no clear change",
  mixed: "mixed",
  unknown: "unknown",
};
const CONF_CLASS: Record<Confidence, string> = {
  low: "pl-chip-red",
  medium: "pl-chip-yellow",
  high: "pl-chip-green",
};

export function WhatIfLabel() {
  return (
    <div className="pl-banner pl-banner-yellow pl-banner-big" role="note">
      {WHATIF_LABEL}
    </div>
  );
}

function AgentTimeline({ run, live }: { run: AgentRun; live: boolean }) {
  return (
    <div className="pl-agent">
      <div className="pl-row pl-wrap">
        <strong>{run.agent}</strong>
        {live && run.events.length === 0 && <span className="pl-muted pl-small">starting…</span>}
        {!live && (
          <span className={`pl-chip ${run.ok ? "pl-chip-green" : "pl-chip-red"}`}>{run.ok ? "ok" : "failed"}</span>
        )}
        {run.used_tools && <span className="pl-chip pl-chip-blue">used tools</span>}
        <span className="pl-small pl-muted">{fmtMs(run.latency_ms)}</span>
        {Object.keys(run.tokens).length > 0 && (
          <span className="pl-small pl-muted">
            tokens {Object.entries(run.tokens).map(([k, v]) => `${k}:${v}`).join(" ")}
          </span>
        )}
      </div>
      {run.error && <div className="pl-small pl-err-text">{run.error}</div>}
      {run.events.length > 0 && (
        <ol className="pl-events">
          {run.events.map((e) => (
            <li key={e.seq} className={e.ok ? "" : "pl-event-bad"}>
              <span className="pl-chip pl-chip-grey pl-chip-sm">{e.kind}</span>{" "}
              {e.tool_name && <code>{e.tool_name}</code>} <span>{e.summary}</span>
              <span className="pl-small pl-muted">
                {e.latency_ms !== null ? ` · ${fmtMs(e.latency_ms)}` : ""}
                {e.tokens && Object.keys(e.tokens).length > 0
                  ? ` · tokens ${Object.entries(e.tokens).map(([k, v]) => `${k}:${v}`).join(" ")}`
                  : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AssessmentCard({ a }: { a: SubsystemAssessment }) {
  return (
    <div className="pl-subcard">
      <div className="pl-row pl-wrap">
        <strong className="pl-card-title">{a.subsystem}</strong>
        {(a.owner_label || a.owner_persona) && (
          <span className="pl-chip pl-chip-grey">{a.owner_label || `owner: ${a.owner_persona}`}</span>
        )}
        <span className="pl-chip pl-chip-blue">{DIR_LABEL[a.direction] ?? a.direction}</span>
        <span className={`pl-chip ${CONF_CLASS[a.confidence] ?? "pl-chip-grey"}`}>confidence: {a.confidence}</span>
      </div>
      <p className="pl-p">{a.impact_summary}</p>
      {a.magnitude_hint && (
        <p className="pl-small">
          <strong>Magnitude:</strong> {a.magnitude_hint}
        </p>
      )}
      {a.tool_numbers_cited.length > 0 && (
        <div className="pl-small">
          <strong>Tool numbers cited:</strong>
          <div className="pl-row pl-wrap pl-gap-top">
            {a.tool_numbers_cited.map((n, i) => (
              <span key={i} className="pl-chip pl-chip-green pl-chip-sm">
                {n}
              </span>
            ))}
          </div>
        </div>
      )}
      {a.caveats.length > 0 && (
        <ul className="pl-list pl-small">
          {a.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function HowItWorksCard({ items }: { items: HowItWorks[] }) {
  return (
    <div className="pl-card pl-card-blue">
      <h3 className="pl-h3 pl-h3-first">How this part works</h3>
      <ul className="pl-plain pl-stack">
        {items.map((h, i) => (
          <li key={`${h.subsystem}-${i}`}>
            <strong>{h.name || h.subsystem}</strong>
            <p className="pl-p">{h.explanation}</p>
            <div className="pl-tiny pl-muted">Source: {h.source || HOW_IT_WORKS_SOURCE}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EffectsElsewhereCard({ items }: { items: EffectElsewhere[] }) {
  return (
    <div className="pl-card pl-card-yellow">
      <h3 className="pl-h3 pl-h3-first">What a change of this size could affect (model-based)</h3>
      <p className="pl-small pl-muted">Modelled from this plant's historical data and generic background; not physics, not causation.</p>
      <ul className="pl-plain pl-stack">
        {items.map((e, i) => (
          <li key={`${e.subsystem}-${i}`} className="pl-subcard">
            <div className="pl-row pl-wrap">
              <strong>{e.subsystem}</strong>
              <span className="pl-chip pl-chip-blue">{DIR_LABEL[e.direction] ?? e.direction}</span>
              <span className={`pl-chip ${CONF_CLASS[e.confidence] ?? "pl-chip-grey"}`}>confidence: {e.confidence}</span>
              {e.basis && <span className="pl-chip pl-chip-grey pl-chip-sm">{e.basis}</span>}
            </div>
            <p className="pl-p">{e.description}</p>
            {e.magnitude_hint && (
              <p className="pl-small">
                <strong>Magnitude:</strong> {e.magnitude_hint}
              </p>
            )}
            {e.tool_numbers_cited.length > 0 && (
              <div className="pl-row pl-wrap">
                {e.tool_numbers_cited.map((n, j) => (
                  <span key={j} className="pl-chip pl-chip-green pl-chip-sm">
                    {n}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NextStepsCard({ items }: { items: NextStep[] }) {
  return (
    <div className="pl-card pl-card-green">
      <h3 className="pl-h3 pl-h3-first">Options to evaluate (human review)</h3>
      <div className="pl-alert pl-alert-warn pl-alert-flat" role="note">
        {NEXT_STEPS_NOTE}
      </div>
      <ol className="pl-stack pl-steps">
        {items.map((st, i) => (
          <li key={i} className="pl-subcard">
            <div className="pl-row pl-wrap">
              <span className="pl-chip pl-chip-blue">{st.kind.replace(/_/g, " ")}</span>
              {st.subsystem && <span className="pl-chip pl-chip-grey pl-chip-sm">{st.subsystem}</span>}
              {st.requires_supervisor_approval && <span className="pl-chip pl-chip-yellow">requires supervisor approval</span>}
            </div>
            <p className="pl-p">
              <strong>{st.action}</strong>
            </p>
            {st.rationale && <p className="pl-small pl-muted">{st.rationale}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Result of a finished (or running) what-if session. */
export function WhatIfResult({ session }: { session: WhatIfSession }) {
  const running = session.status === "running";
  const ans = session.answer;
  return (
    <div className="pl-stack">
      <div className="pl-row pl-wrap">
        {session.mode === "meta_live" ? (
          <span className="pl-chip pl-chip-green">meta_live{session.meta_model ? ` · ${session.meta_model}` : ""}</span>
        ) : (
          <span className="pl-chip pl-chip-grey">offline (no Meta call)</span>
        )}
        <span className="pl-small pl-muted">{session.mode_label}</span>
        <span className="pl-chip pl-chip-blue">status: {session.status}</span>
        {session.wall_ms !== null && <span className="pl-small pl-muted">wall time {fmtMs(session.wall_ms)}</span>}
      </div>

      {session.status === "needs_review" && (
        <div className="pl-alert pl-alert-warn" role="alert">
          Needs review: the agent output did not fully pass validation. Treat the text below with extra caution.
        </div>
      )}
      {session.status === "failed" && (
        <div className="pl-alert pl-alert-err" role="alert">
          What-if run failed{session.error ? `: ${session.error}` : "."}
        </div>
      )}
      {session.validation_errors.length > 0 && (
        <div className="pl-alert pl-alert-warn">
          <strong>Validation errors</strong>
          <ul className="pl-list">
            {session.validation_errors.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        </div>
      )}

      {ans && (
        <>
          <div className="pl-small">
            <strong>Change:</strong> {ans.change.measurement} {fmtSigned(ans.change.delta)} {ans.change.unit}{" "}
            {ans.change.within_training_range ? (
              <span className="pl-chip pl-chip-green pl-chip-sm">within training range</span>
            ) : (
              <span className="pl-chip pl-chip-red pl-chip-sm">outside training range</span>
            )}
            {ans.question && (
              <>
                <br />
                <strong>Question:</strong> {ans.question}
              </>
            )}
          </div>

          {(ans.how_it_works ?? []).length > 0 && <HowItWorksCard items={ans.how_it_works} />}
          {(ans.effects_elsewhere ?? []).length > 0 && <EffectsElsewhereCard items={ans.effects_elsewhere} />}
          {(ans.recommended_next_steps ?? []).length > 0 && <NextStepsCard items={ans.recommended_next_steps} />}

          <h3 className="pl-h3">Per-subsystem agent assessments</h3>
          <div className="pl-grid">
            {ans.subsystem_assessments.map((a, i) => (
              <AssessmentCard key={`${a.subsystem}-${i}`} a={a} />
            ))}
          </div>

          {ans.cross_impacts.length > 0 && (
            <>
              <h3 className="pl-h3">Cross-impacts</h3>
              <ul className="pl-list">
                {ans.cross_impacts.map((c, i) => (
                  <li key={i}>
                    {c.subsystems.length > 0 && <strong>{c.subsystems.join(" ↔ ")}: </strong>}
                    {c.description}
                    {c.basis && <span className="pl-chip pl-chip-grey pl-chip-sm">{c.basis}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}

          {ans.what_to_check_before_acting.length > 0 && (
            <>
              <h3 className="pl-h3">What to check before acting</h3>
              <ul className="pl-list">
                {ans.what_to_check_before_acting.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </>
          )}
          <p className="pl-small pl-muted">{ans.disclaimer}</p>
        </>
      )}

      {session.agents.length > 0 && (
        <details className="pl-details" open={running}>
          <summary>Agent timeline ({session.agents.length} agent{session.agents.length === 1 ? "" : "s"})</summary>
          {session.agents.map((r) => (
            <AgentTimeline key={r.agent} run={r} live={running} />
          ))}
        </details>
      )}
    </div>
  );
}

function PreviewPanel({ s, loading, error }: { s: Sensitivity | null; loading: boolean; error: string | null }) {
  if (error) return <div className="pl-alert pl-alert-err">{error}</div>;
  if (!s) return <div className="pl-muted pl-small">{loading ? "Computing preview…" : "Move the slider to preview."}</div>;
  const me = s.model_effect;
  const tr = s.train_range_check;
  return (
    <div className={`pl-preview ${loading ? "pl-dim" : ""}`}>
      <div className="pl-h4">Instant deterministic preview (no LLM)</div>
      {me.applicable ? (
        <div className="pl-stats">
          <div className="pl-stat">
            <div className="pl-stat-v">
              {fmtSigned(me.delta_tey_mean)} {me.unit}
            </div>
            <div className="pl-stat-l">ΔTEY mean</div>
          </div>
          <div className="pl-stat">
            <div className="pl-stat-v">{fmtSigned(me.delta_tey_min)}</div>
            <div className="pl-stat-l">min</div>
          </div>
          <div className="pl-stat">
            <div className="pl-stat-v">{fmtSigned(me.delta_tey_max)}</div>
            <div className="pl-stat-l">max</div>
          </div>
          <div className="pl-stat">
            <div className="pl-stat-v">{fmt(me.expected_tey_base_mean, 1)}</div>
            <div className="pl-stat-l">base TEY mean</div>
          </div>
        </div>
      ) : (
        <div className="pl-small">Model effect not applicable: {me.note}</div>
      )}
      {me.applicable && me.note && <div className="pl-small pl-muted">{me.note}</div>}
      <div className="pl-row pl-wrap pl-gap-top">
        {tr.ood_flag ? (
          <span className="pl-chip pl-chip-red">OOD: outside training range</span>
        ) : (
          <span className="pl-chip pl-chip-green">within training range</span>
        )}
        <span className="pl-small pl-muted">
          {tr.rows_outside}/{tr.rows} rows outside [{fmt(tr.train_min)}, {fmt(tr.train_max)}] after perturbation
        </span>
      </div>
      <div className="pl-small pl-muted">
        Base window: {s.base.basis} ({s.base.rows} rows) · model {me.model_version ?? "n/a"}
      </div>

      {s.co_movement.items.length > 0 && (
        <div className="pl-gap-top">
          <div className="pl-h4">Top co-movements</div>
          <div className="pl-small pl-muted">
            {ASSOCIATION_LABEL} ({s.co_movement.label}; n={s.co_movement.n_rows})
          </div>
          <table className="pl-table">
            <thead>
              <tr>
                <th>Measurement</th>
                <th>Pearson r</th>
                <th>Implied change</th>
              </tr>
            </thead>
            <tbody>
              {s.co_movement.items.slice(0, 6).map((c) => (
                <tr key={c.measurement}>
                  <td>{c.measurement}</td>
                  <td>{fmt(c.pearson_r, 2)}</td>
                  <td>
                    {fmtSigned(c.implied_change_for_delta)} {c.unit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s.caveats.length > 0 && (
        <ul className="pl-list pl-small pl-muted">
          {s.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WhatIfConsole({ caseId }: { caseId?: string }) {
  const [measurements, setMeasurements] = useState<MeasurementInfo[]>([]);
  const [mError, setMError] = useState<string | null>(null);
  const [key, setKey] = useState<string>("");
  const [delta, setDelta] = useState<number>(0);
  const [question, setQuestion] = useState("");

  const [preview, setPreview] = useState<Sensitivity | null>(null);
  const [pLoading, setPLoading] = useState(false);
  const [pError, setPError] = useState<string | null>(null);

  const [session, setSession] = useState<WhatIfSession | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number>(0);

  useEffect(() => {
    const c = new AbortController();
    getMeasurements(c.signal)
      .then((m) => {
        setMeasurements(m);
        setKey((cur) => cur || (m.find((x) => x.key === "AFDP")?.key ?? m[0]?.key ?? ""));
      })
      .catch((e) => {
        if (!c.signal.aborted) setMError(errorMessage(e));
      });
    return () => c.abort();
  }, []);

  const info = useMemo(() => measurements.find((m) => m.key === key) ?? null, [measurements, key]);

  // Reset delta when measurement changes.
  useEffect(() => {
    setDelta(0);
    setPreview(null);
  }, [key]);

  // Debounced deterministic preview.
  useEffect(() => {
    if (!key || delta === 0) {
      setPreview(null);
      setPError(null);
      setPLoading(false);
      return;
    }
    const c = new AbortController();
    setPLoading(true);
    const t = window.setTimeout(() => {
      getSensitivity(key, delta, caseId, c.signal)
        .then((s) => {
          setPreview(s);
          setPError(null);
          setPLoading(false);
        })
        .catch((e) => {
          if (c.signal.aborted) return;
          setPError(errorMessage(e));
          setPLoading(false);
        });
    }, 350);
    return () => {
      window.clearTimeout(t);
      c.abort();
    };
  }, [key, delta, caseId]);

  const sessionId = session?.session_id;
  const running = session?.status === "running";

  // Poll while running.
  useEffect(() => {
    if (!sessionId || !running) return;
    let alive = true;
    const c = new AbortController();
    const tick = window.setInterval(() => {
      getWhatIf(sessionId, c.signal)
        .then((s) => {
          if (alive) setSession(s);
        })
        .catch((e) => {
          if (alive && !c.signal.aborted) setRunError(errorMessage(e));
        });
    }, POLL_MS);
    return () => {
      alive = false;
      c.abort();
      window.clearInterval(tick);
    };
  }, [sessionId, running]);

  // Elapsed timer.
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 500);
    return () => window.clearInterval(t);
  }, [running]);

  const ask = useCallback(async () => {
    if (!key || delta === 0) return;
    setRunError(null);
    setStarting(true);
    setSession(null);
    startedAt.current = Date.now();
    setElapsed(0);
    try {
      const s = await startWhatIf({ case_id: caseId ?? null, question: question.trim(), measurement: key, delta });
      setSession(s);
    } catch (e) {
      setRunError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  }, [key, delta, caseId, question]);

  const bound = info?.max_abs_delta ?? 1;
  const step = info?.step ?? 0.01;

  return (
    <section className="pl-root pl-console" aria-label="What-if console">
      <WhatIfLabel />
      <div className="pl-card">
        <h2 className="pl-h2">What-if: change one measurement</h2>
        <p className="pl-small pl-muted">
          Base window: {caseId ? `case ${caseId}` : "default 2014 window, rows [1200, 1320)"}. Read-only; nothing is sent to
          any control system.
        </p>
        {mError && <div className="pl-alert pl-alert-err">{mError}</div>}

        <div className="pl-form">
          <label className="pl-field">
            <span className="pl-label">Measurement</span>
            <select className="pl-select" value={key} onChange={(e) => setKey(e.target.value)} disabled={measurements.length === 0}>
              {measurements.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.key} — {m.name} ({m.unit}){m.is_model_feature ? "" : " · not a model feature"}
                </option>
              ))}
            </select>
          </label>

          <label className="pl-field">
            <span className="pl-label">
              Delta: <strong>{fmtSigned(delta, step < 0.1 ? 2 : 1)}</strong> {info?.unit ?? ""}
              {info && <span className="pl-muted pl-small"> (±{fmt(info.max_abs_delta)} max; train σ {fmt(info.train_std)})</span>}
            </span>
            <input
              className="pl-range"
              type="range"
              min={-bound}
              max={bound}
              step={step}
              value={delta}
              onChange={(e) => setDelta(Number(e.target.value))}
              disabled={!info}
              aria-label="Delta"
            />
            <input
              className="pl-input pl-input-num"
              type="number"
              min={-bound}
              max={bound}
              step={step}
              value={delta}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (!Number.isNaN(v)) setDelta(Math.max(-bound, Math.min(bound, v)));
              }}
              disabled={!info}
              aria-label="Delta value"
            />
          </label>

          <label className="pl-field">
            <span className="pl-label">Question (optional)</span>
            <textarea
              className="pl-textarea"
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. What happens downstream if the inlet filter differential pressure rises?"
            />
          </label>
        </div>

        <PreviewPanel s={preview} loading={pLoading} error={pError} />

        <div className="pl-row pl-wrap pl-gap-top">
          <button className="pl-btn pl-btn-green pl-btn-lg" disabled={!key || delta === 0 || starting || running} onClick={ask}>
            {starting ? "Starting…" : running ? "Agents running…" : "Ask the plant agents"}
          </button>
          {delta === 0 && <span className="pl-small pl-muted">Set a non-zero delta first.</span>}
          {running && (
            <span className="pl-chip pl-chip-yellow" aria-live="polite">
              running · {elapsed}s elapsed (live agents typically take 30–90 s)
            </span>
          )}
        </div>
        {runError && (
          <div className="pl-alert pl-alert-err" role="alert">
            {runError}
          </div>
        )}
      </div>

      {session && (
        <div className="pl-card">
          <h2 className="pl-h2">{running ? "Live agent run" : "Plant agents' answer"}</h2>
          <div className="pl-small pl-muted">session {session.session_id} · persona {session.persona}</div>
          <WhatIfResult session={session} />
          <p className="pl-small pl-muted">{session.label}</p>
        </div>
      )}
    </section>
  );
}
