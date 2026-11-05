import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { ErrorBanner } from "../../components/Feedback";
import { Chip } from "./badges";
import { PanelTitle } from "./ResultPanels";
import { recordDecision } from "./api";
import type { Persona } from "../../plant/types";
import type { Decision, DeliberationSession } from "./types";

const DECISION_LABEL: Record<Decision, string> = { approve_plan: "Approve plan", reject: "Reject", defer: "Defer" };

export function DecisionPanel({
  session,
  personas,
  persona,
  onPersona,
  onUpdated,
}: {
  session: DeliberationSession;
  personas: Persona[];
  persona: string;
  onPersona: (id: string) => void;
  onUpdated: (s: DeliberationSession) => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<Decision | null>(null);
  const [error, setError] = useState<unknown>(null);
  const enabled = session.status === "completed" || session.status === "needs_review";
  const latest = session.decisions.length ? session.decisions[session.decisions.length - 1] : null;

  async function submit(decision: Decision) {
    setBusy(decision);
    setError(null);
    try {
      const s = await recordDecision(session.deliberation_id, {
        decision,
        persona,
        comment: comment.trim() ? comment.trim() : null,
      });
      onUpdated(s);
      setComment("");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel" aria-label="Human decision">
      <PanelTitle>Human decision</PanelTitle>
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-ink-300">
          The agents only advise. Your choice is recorded and routed to the responsible people; nothing is executed and nothing is written to any plant system.
        </p>
        {!enabled ? (
          <p className="text-sm text-ink-400" role="status">
            {session.status === "running" ? "Available once the deliberation has finished." : "Decisions cannot be recorded for a failed deliberation."}
          </p>
        ) : null}
        <div className="grid gap-3 md:grid-cols-[14rem_1fr]">
          <label className="flex flex-col gap-1.5">
            <span className="label">Deciding as</span>
            <select className="input" value={persona} onChange={(e) => onPersona(e.target.value)} disabled={!enabled || busy !== null}>
              {personas.map((p) => (
                <option key={p.persona_id} value={p.persona_id}>
                  {p.name} ({p.role})
                </option>
              ))}
              {!personas.some((p) => p.persona_id === persona) ? <option value={persona}>{persona}</option> : null}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="label">Comment (optional)</span>
            <textarea
              className="input h-auto min-h-[2.5rem] py-2"
              rows={2}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              disabled={!enabled || busy !== null}
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" disabled={!enabled || busy !== null} onClick={() => void submit("approve_plan")}>
            {busy === "approve_plan" ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />} {DECISION_LABEL.approve_plan}
          </button>
          <button type="button" className="btn-danger" disabled={!enabled || busy !== null} onClick={() => void submit("reject")}>
            {busy === "reject" ? <Loader2 size={16} className="animate-spin" /> : <XCircle size={16} />} {DECISION_LABEL.reject}
          </button>
          <button type="button" className="btn-secondary" disabled={!enabled || busy !== null} onClick={() => void submit("defer")}>
            {busy === "defer" ? <Loader2 size={16} className="animate-spin" /> : <Clock size={16} />} {DECISION_LABEL.defer}
          </button>
        </div>
        {error ? <ErrorBanner error={error} title="Could not record the decision" /> : null}

        <div aria-live="polite">
          {latest ? (
            <div className="rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-900">
              <div className="font-semibold">
                Recorded; routed to {latest.routed_to_label || latest.routed_to}; nothing was executed
              </div>
              <div className="mt-0.5">
                {DECISION_LABEL[latest.decision]} by {latest.persona_label || latest.persona}
              </div>
              {latest.routing_note ? <div className="mt-1">{latest.routing_note}</div> : null}
              {latest.message ? <div className="mt-1 text-green-800">{latest.message}</div> : null}
            </div>
          ) : null}
        </div>

        {session.decisions.length > 0 ? (
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-300">Decision history</h3>
            <ol className="space-y-1.5 text-sm text-ink-100">
              {session.decisions.map((d, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-ink-700/60 pb-1.5 last:border-b-0">
                  <Chip>{DECISION_LABEL[d.decision]}</Chip>
                  <span className="font-semibold">{d.persona_label || d.persona}</span>
                  <span className="font-mono text-xs text-ink-400">{d.recorded_at_utc}</span>
                  <span className="text-ink-300">routed to {d.routed_to_label || d.routed_to}</span>
                  {d.comment ? <span className="w-full text-ink-200">“{d.comment}”</span> : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </div>
    </section>
  );
}
