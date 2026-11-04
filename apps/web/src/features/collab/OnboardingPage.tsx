import { ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBanner, InfoBanner, Spinner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { getPersonas } from "../../plant/api";
import { usePersona } from "../../plant/persona";
import type { Persona } from "../../plant/types";
import { generateOnboarding, getLatestOnboarding } from "./api";
import type { OnboardingBrief } from "./types";
import "../../plant/plant.css";
import "./collab.css";

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function OnboardingPage() {
  const [current] = usePersona();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState<string>(current);
  const [brief, setBrief] = useState<OnboardingBrief | null>(null);
  const [loadingLatest, setLoadingLatest] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [checked, setChecked] = useState<Record<number, boolean>>({});

  useEffect(() => {
    const c = new AbortController();
    getPersonas(c.signal)
      .then((r) => setPersonas(r.personas))
      .catch(() => {
        /* names fall back to ids */
      });
    return () => c.abort();
  }, []);

  const nameOf = useMemo(() => {
    const m = new Map(personas.map((p) => [p.persona_id, p]));
    return (id: string) => {
      const p = m.get(id);
      return p ? `${p.name} (${p.role})` : id;
    };
  }, [personas]);

  // "Load latest" on persona change
  useEffect(() => {
    const c = new AbortController();
    setLoadingLatest(true);
    setError(null);
    setChecked({});
    getLatestOnboarding(personaId, c.signal)
      .then((r) => {
        setBrief(r.brief);
        setLoadingLatest(false);
      })
      .catch((e) => {
        if (c.signal.aborted) return;
        setBrief(null);
        setError(e);
        setLoadingLatest(false);
      });
    return () => c.abort();
  }, [personaId]);

  useEffect(() => {
    if (!generating) return;
    setElapsed(0);
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [generating]);

  const onGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const b = await generateOnboarding(personaId);
      setBrief(b);
      setChecked({});
    } catch (e) {
      setError(e);
    } finally {
      setGenerating(false);
    }
  };

  const b = brief?.brief;

  return (
    <div className="cb-root">
      <PageHeader
        title="Onboarding"
        subtitle="A role-specific guide for a new joiner, drafted from this plant's own data and routing. It is a starting point, not an authority."
        right={<SourceBadge variant="review" />}
      />

      <div className="cb-section" style={{ marginBottom: 16 }}>
        <div className="cb-row">
          <label className="cb-row">
            <span className="cb-small cb-muted">Role</span>
            <select
              className="cb-input"
              value={personaId}
              onChange={(e) => setPersonaId(e.target.value)}
              disabled={generating}
              aria-label="Choose the role to onboard"
            >
              {!personas.some((p) => p.persona_id === personaId) ? <option value={personaId}>{personaId}</option> : null}
              {personas.map((p) => (
                <option key={p.persona_id} value={p.persona_id}>
                  {p.name} — {p.role}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="cb-btn cb-btn-primary" onClick={() => void onGenerate()} disabled={generating}>
            {generating ? "Generating…" : "Generate onboarding brief"}
          </button>
          {generating ? (
            <span className="cb-row" role="status">
              <Spinner /> <span className="cb-small">Drafting with the agent ({elapsed} s, live drafting can take 1-2 minutes)</span>
            </span>
          ) : null}
        </div>
        <p className="cb-small cb-muted" style={{ margin: "8px 0 0" }}>
          Generating creates a new draft each time and only writes a log row. Nothing is sent anywhere.
        </p>
      </div>

      {error ? <ErrorBanner error={error} title="Onboarding request failed" className="mb-4" /> : null}
      {loadingLatest ? <div className="cb-muted" role="status">Loading the latest brief…</div> : null}
      {!loadingLatest && !brief && !error ? (
        <InfoBanner>No onboarding brief exists for this role yet. Use "Generate onboarding brief" to draft one.</InfoBanner>
      ) : null}

      {brief && b ? (
        <div className="cb-stack">
          <div className="cb-badge-big" role="note">
            <ShieldAlert size={20} aria-hidden="true" />
            <div>
              <div>{brief.badge}</div>
              <div className="cb-row" style={{ fontWeight: 500, marginTop: 4 }}>
                <span className={`pl-chip ${brief.mode === "meta_live" ? "pl-chip-green" : "pl-chip-grey"}`}>
                  {brief.mode === "meta_live" ? "meta_live" : "offline fallback — deterministic"}
                </span>
                <span className="cb-small">{brief.source_label}</span>
              </div>
              <div className="cb-small" style={{ fontWeight: 500, marginTop: 4 }}>
                {brief.brief_id} · {fmtTs(brief.created_at_utc)} · role {nameOf(brief.persona)}
                {brief.meta_model ? ` · ${brief.meta_model}` : ""}
                {brief.meta_calls ? ` · ${brief.meta_calls} model call(s)` : ""}
                {brief.latency_ms !== null ? ` · ${(brief.latency_ms / 1000).toFixed(1)} s` : ""}
              </div>
            </div>
          </div>

          {brief.fallback_reason ? (
            <div className="pl-alert pl-alert-warn">
              <strong>Fallback reason: </strong>
              {brief.fallback_reason}
            </div>
          ) : null}
          {brief.validation_errors.length ? (
            <details className="pl-details">
              <summary>Validation notes ({brief.validation_errors.length})</summary>
              <ul className="cb-small" style={{ margin: "6px 0 0" }}>
                {brief.validation_errors.map((v, i) => (
                  <li key={i}>{v}</li>
                ))}
              </ul>
            </details>
          ) : null}

          <section className="cb-section" aria-label="Role">
            <h2 className="cb-h2">Your role</h2>
            <p style={{ margin: 0 }}>{b.role_summary}</p>
          </section>

          <section className="cb-section" aria-label="How the plant works">
            <h2 className="cb-h2">How the plant works</h2>
            {b.how_the_plant_works.map((s, i) => (
              <div key={i}>
                <h3 className="cb-h3">{s.subsystem}</h3>
                <p style={{ margin: 0 }}>{s.explanation}</p>
              </div>
            ))}
          </section>

          <section className="cb-section" aria-label="What you watch">
            <h2 className="cb-h2">What you watch</h2>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {b.what_you_watch.map((w, i) => (
                <li key={i}>
                  <strong>{w.measurement}</strong> — {w.why}
                </li>
              ))}
            </ul>
          </section>

          <section className="cb-section" aria-label="Who you work with">
            <h2 className="cb-h2">Who you work with</h2>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {b.who_you_work_with.map((w, i) => (
                <li key={i}>
                  <strong>{nameOf(w.persona)}</strong> — {w.when}
                </li>
              ))}
            </ul>
          </section>

          <section className="cb-section" aria-label="Current open items">
            <h2 className="cb-h2">Current open items</h2>
            {b.current_open_items.length === 0 ? (
              <div className="pl-empty">No open items right now.</div>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {b.current_open_items.map((id) => (
                  <li key={id}>
                    <Link to={`/investigations/${encodeURIComponent(id)}`} className="cb-link">
                      {id}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="cb-section" aria-label="First-week checklist">
            <h2 className="cb-h2">First-week checklist</h2>
            <p className="cb-small cb-muted" style={{ margin: "0 0 4px" }}>Ticks are kept in this browser tab only.</p>
            {b.first_week_checklist.map((item, i) => (
              <label key={i} className="cb-check">
                <input type="checkbox" checked={!!checked[i]} onChange={(e) => setChecked((c) => ({ ...c, [i]: e.target.checked }))} />
                <span>{item}</span>
              </label>
            ))}
          </section>

          <p className="cb-small cb-muted" style={{ margin: 0 }}>{b.disclaimer}</p>
        </div>
      ) : null}
    </div>
  );
}
