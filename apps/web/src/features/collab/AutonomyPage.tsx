import { Bot, RefreshCw, UserCheck, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../api/client";
import { ErrorBanner, InfoBanner, PanelSkeleton, Spinner } from "../../components/Feedback";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { usePersona } from "../../plant/persona";
import { applyPolicyToExisting, getPolicy, listDecisions, reopenDecision } from "./api";
import type { AutoDecision, AutonomyLevel, DecisionCounts, PolicyAction, PolicyResponse } from "./types";
import "../../plant/plant.css";
import "./collab.css";

const POLL_MS = 15_000;

const LEVELS: { id: AutonomyLevel; title: string; tag: string; tagCls: string }[] = [
  { id: "agent_auto", title: "Agent does it automatically (read-only, logged)", tag: "AGENT", tagCls: "cb-tag-agent" },
  { id: "human_review", title: "Agent drafts, human decides", tag: "AGENT + HUMAN", tagCls: "cb-tag-amber" },
  { id: "human_only", title: "Humans only — no software path", tag: "HUMAN", tagCls: "cb-tag-human" },
];

const STORY: { n: number; title: string; to: string; who: { tag: string; cls: string; note: string }; text: string }[] = [
  {
    n: 1,
    title: "Alert raised",
    to: "/investigations",
    who: { tag: "AGENT", cls: "cb-tag-agent", note: "automatic, read-only" },
    text: "The investigator agent screens the data and drafts a case with evidence.",
  },
  {
    n: 2,
    title: "Routed to technician + supervisor",
    to: "/inbox",
    who: { tag: "AGENT", cls: "cb-tag-agent", note: "automatic routing" },
    text: "A work request and notifications land in the right inboxes.",
  },
  {
    n: 3,
    title: "Technician asks the plant: what-if + domino map",
    to: "/ask",
    who: { tag: "HUMAN asks", cls: "cb-tag-human", note: "agents answer" },
    text: "The person poses the question; deterministic tools compute and agents explain.",
  },
  {
    n: 4,
    title: "Supervisor approves next steps",
    to: "/inbox",
    who: { tag: "HUMAN", cls: "cb-tag-human", note: "decision" },
    text: "Only a person accepts, rejects or asks for more evidence.",
  },
  {
    n: 5,
    title: "Handover drafted",
    to: "/ops",
    who: { tag: "AGENT drafts", cls: "cb-tag-agent", note: "human signs off" },
    text: "The shift handover note is drafted; a person reviews and signs off.",
  },
  {
    n: 6,
    title: "New joiner reads onboarding",
    to: "/onboarding",
    who: { tag: "AGENT drafts", cls: "cb-tag-agent", note: "human verifies" },
    text: "A role-specific guide is drafted; the supervisor verifies it.",
  },
];

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function decisionChip(d: AutoDecision["decision"]): { cls: string; label: string } {
  if (d === "auto_triaged_no_action") return { cls: "pl-chip-blue", label: "Auto-triaged: no action (logged)" };
  if (d === "requires_human") return { cls: "pl-chip-yellow", label: "Requires human" };
  return { cls: "pl-chip-red", label: "Human reopened" };
}

function ActionRow({ a }: { a: PolicyAction }) {
  return (
    <li className="cb-action">
      <div className="cb-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <strong>{a.action}</strong>
        <span className={`pl-chip pl-chip-sm ${a.reversible ? "pl-chip-grey" : "pl-chip-red"}`}>
          {a.reversible ? "reversible" : "not reversible"}
        </span>
      </div>
      <div className="cb-small cb-muted">Actor: {a.actor}</div>
      <div className="cb-small">{a.why}</div>
      {a.link ? (
        <Link to={a.link} className="cb-link cb-small">
          Open {a.link}
        </Link>
      ) : null}
    </li>
  );
}

export default function AutonomyPage() {
  const [persona] = usePersona();
  const [policy, setPolicy] = useState<PolicyResponse | null>(null);
  const [decisions, setDecisions] = useState<AutoDecision[]>([]);
  const [counts, setCounts] = useState<DecisionCounts | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [p, d] = await Promise.all([getPolicy(signal), listDecisions({ limit: 20 }, signal)]);
      if (signal?.aborted) return;
      setPolicy(p);
      setDecisions(d.decisions);
      setCounts(d.counts ?? p.counts);
      setError(null);
    } catch (e) {
      if (signal?.aborted) return;
      setError(e);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    const t = window.setInterval(() => void load(c.signal), POLL_MS);
    return () => {
      c.abort();
      window.clearInterval(t);
    };
  }, [load]);

  const onReopen = async (d: AutoDecision) => {
    if (
      !window.confirm(
        `Reopen case ${d.case_id} for human review? This only changes the log and puts the case back in front of people; nothing touches the plant.`,
      )
    )
      return;
    setBusy(d.decision_id);
    setActionErr(null);
    setActionMsg(null);
    try {
      await reopenDecision(d.decision_id, { persona, comment: "Reopened from Who decides what" });
      setActionMsg(`Case ${d.case_id} reopened for human review.`);
      await load();
    } catch (e) {
      setActionErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const onApply = async () => {
    setBusy("apply");
    setActionErr(null);
    setActionMsg(null);
    try {
      const r = await applyPolicyToExisting();
      setActionMsg(`Policy applied (logging only): ${r.applied} stored case(s) newly decided, ${r.already_decided} already had a decision.`);
      await load();
    } catch (e) {
      setActionErr(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="cb-root">
      <PageHeader
        title="Who decides what"
        subtitle="Agents do the read-only legwork automatically; people make every decision that matters; nothing in ThermoMind can operate the plant."
        right={<SourceBadge variant="review" />}
      />

      {error ? <ErrorBanner error={error} title="Could not load the autonomy policy" onRetry={() => void load()} className="mb-4" /> : null}
      {loading && !policy ? <PanelSkeleton lines={6} /> : null}

      {policy ? (
        <div className="cb-stack">
          {/* counters */}
          <section aria-label="Live decision counters">
            <div className="cb-grid4">
              <KpiCard label="Auto-triaged, no action" value={counts?.auto_triaged_no_action ?? "—"} caption="Logged by the policy; a person can reopen any of them" icon={<Bot size={16} />} />
              <KpiCard label="Requires human" value={counts?.requires_human ?? "—"} caption="Routed to people for a decision" tone="amber" icon={<UserCheck size={16} />} />
              <KpiCard label="Human override: reopened" value={counts?.human_override_reopened ?? "—"} caption="Auto-triage overruled by a person" icon={<Users size={16} />} />
            </div>
            <p className="cb-small cb-muted" style={{ margin: "6px 0 0" }}>
              Refreshes every 15 s. Policy {policy.policy_id}: {policy.title}. Total decisions logged: {counts?.total ?? 0}.
            </p>
          </section>

          {/* three levels */}
          <section aria-label="Autonomy levels">
            <div className="cb-grid3">
              {LEVELS.map((lv) => {
                const acts = policy.actions.filter((a) => a.level === lv.id);
                return (
                  <div key={lv.id} className={`cb-level cb-level-${lv.id}`}>
                    <div className="cb-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                      <h2 className="cb-h2" style={{ fontSize: 16 }}>{lv.title}</h2>
                      <span className={`cb-tag ${lv.tagCls}`}>{lv.tag}</span>
                    </div>
                    {policy.levels[lv.id] ? <p className="cb-small cb-muted" style={{ margin: "0 0 4px" }}>{policy.levels[lv.id]}</p> : null}
                    {acts.length === 0 ? (
                      <div className="pl-empty">No actions at this level.</div>
                    ) : (
                      <ul className="cb-plain" style={{ margin: 0 }}>
                        {acts.map((a) => (
                          <ActionRow key={a.action_id} a={a} />
                        ))}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
            {policy.note ? <p className="cb-small cb-muted" style={{ margin: "8px 0 0" }}>{policy.note}</p> : null}
          </section>

          {/* P-01 conditions */}
          <section className="cb-section" aria-label="Auto-triage conditions">
            <h2 className="cb-h2">When no human intervention is needed ({policy.policy_id})</h2>
            <p className="cb-small cb-muted" style={{ margin: "0 0 6px" }}>
              A case is logged as "auto-triaged, no action" only when every condition below holds. This is read-only
              triage and logging: nothing is sent to or changed in the plant, and a person can reopen any decision.
            </p>
            <ol style={{ margin: 0, paddingLeft: 20 }}>
              {policy.auto_triage_conditions.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ol>
          </section>

          {/* decisions */}
          <section className="cb-section" aria-label="Recent decisions">
            <div className="cb-row" style={{ justifyContent: "space-between" }}>
              <h2 className="cb-h2">Recent decisions</h2>
              <span className="cb-row">
                <button type="button" className="cb-btn cb-btn-sm" onClick={() => void load()} aria-label="Refresh decisions">
                  <RefreshCw size={13} style={{ verticalAlign: "-2px" }} /> Refresh
                </button>
                <button type="button" className="cb-btn cb-btn-sm cb-btn-warn" onClick={() => void onApply()} disabled={busy !== null}>
                  {busy === "apply" ? <Spinner className="inline" /> : null} Apply policy to stored cases (logging only)
                </button>
              </span>
            </div>
            {actionMsg ? <InfoBanner className="mb-2">{actionMsg}</InfoBanner> : null}
            {actionErr ? (
              <div className="pl-alert pl-alert-err" role="alert">
                {actionErr}
              </div>
            ) : null}
            {decisions.length === 0 ? (
              <div className="pl-empty">No decisions logged yet. Use "Apply policy to stored cases" to log decisions for existing cases.</div>
            ) : (
              <div className="cb-table-wrap">
                <table className="cb-table">
                  <caption className="cb-small cb-muted" style={{ textAlign: "left", paddingBottom: 4 }}>
                    Latest 20 policy decisions, newest first
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Time</th>
                      <th scope="col">Case</th>
                      <th scope="col">Decision</th>
                      <th scope="col">Reason</th>
                      <th scope="col">Routed to</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.map((d) => {
                      const chip = decisionChip(d.decision);
                      return (
                        <tr key={d.decision_id}>
                          <td className="cb-small">{fmtTs(d.ts_utc)}</td>
                          <td>
                            <Link to={`/investigations/${encodeURIComponent(d.case_id)}`} className="cb-link">
                              {d.case_id}
                            </Link>
                            {d.synthetic ? (
                              <div>
                                <span className="pl-chip pl-chip-synthetic pl-chip-sm">SYNTHETIC OVERLAY</span>
                              </div>
                            ) : null}
                          </td>
                          <td>
                            <span className={`pl-chip ${chip.cls}`} style={{ whiteSpace: "normal" }}>
                              {chip.label}
                            </span>
                            {d.severity ? <div className="cb-small cb-muted">severity {d.severity}</div> : null}
                          </td>
                          <td className="cb-small">{d.reason}</td>
                          <td className="cb-small">{d.routed_personas.length ? d.routed_personas.join(", ") : "—"}</td>
                          <td>
                            {d.decision === "auto_triaged_no_action" ? (
                              <button
                                type="button"
                                className="cb-btn cb-btn-sm"
                                disabled={busy !== null}
                                onClick={() => void onReopen(d)}
                                aria-label={`Reopen case ${d.case_id} for human review`}
                              >
                                {busy === d.decision_id ? "Reopening…" : "Reopen for human review"}
                              </button>
                            ) : (
                              <span className="cb-small cb-muted">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* story */}
          <section className="cb-section" aria-label="Collaboration story">
            <h2 className="cb-h2">Collaboration story — from alert to onboarding</h2>
            <p className="cb-small cb-muted" style={{ margin: "0 0 8px" }}>
              Each step opens the real page. The tag says who acts: agents only do read-only work and drafts.
            </p>
            <ol className="cb-story cb-plain">
              {STORY.map((s) => (
                <li key={s.n} style={{ display: "flex" }}>
                  <Link to={s.to} className="cb-story-step" style={{ flex: 1 }}>
                    <span className="cb-row">
                      <span className="cb-step" aria-hidden="true">{s.n}</span>
                      <strong>{s.title}</strong>
                    </span>
                    <span className="cb-row">
                      <span className={`cb-tag ${s.who.cls}`}>{s.who.tag}</span>
                      <span className="cb-small cb-muted">{s.who.note}</span>
                    </span>
                    <span className="cb-small">{s.text}</span>
                  </Link>
                </li>
              ))}
            </ol>
          </section>
        </div>
      ) : null}
    </div>
  );
}
