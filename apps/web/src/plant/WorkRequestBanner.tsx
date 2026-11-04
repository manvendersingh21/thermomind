import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, getPersonas, listWorkRequests } from "./api";
import type { WorkRequest, WorkRequestStatus } from "./types";
import { DELIVERY_NOTE } from "./types";
import "./plant.css";

function statusClass(s: WorkRequestStatus): string {
  if (s === "open") return "pl-chip-yellow";
  if (s === "acknowledged") return "pl-chip-blue";
  if (s === "done") return "pl-chip-green";
  return "pl-chip-grey";
}

/** Shows the work requests (assignee / supervisor / notified) generated for a case. */
export function WorkRequestBanner({ caseId }: { caseId: string }) {
  const [items, setItems] = useState<WorkRequest[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    setItems(null);
    setError(null);
    listWorkRequests({ case_id: caseId }, c.signal)
      .then(setItems)
      .catch((e) => {
        if (!c.signal.aborted) setError(errorMessage(e));
      });
    getPersonas(c.signal)
      .then((r) => setNames(Object.fromEntries(r.personas.map((p) => [p.persona_id, p.name]))))
      .catch(() => undefined);
    return () => c.abort();
  }, [caseId]);

  if (error) {
    return (
      <div className="pl-root pl-alert pl-alert-warn" role="note">
        Work requests unavailable: {error}
      </div>
    );
  }
  if (!items || items.length === 0) return null;

  return (
    <section className="pl-root pl-card pl-card-yellow" aria-label="Work requests for this case">
      <h2 className="pl-h2">Work requests for this case</h2>
      <ul className="pl-plain pl-stack">
        {items.map((w) => (
          <li key={w.id} className="pl-subcard">
            <div className="pl-assign">{w.assignment_label || `Assigned to ${names[w.assigned_persona] ?? w.assigned_persona}`}</div>
            <div className="pl-row pl-wrap">
              <span className={`pl-chip ${statusClass(w.status)}`}>{w.status}</span>
              <span className="pl-chip pl-chip-grey">severity: {w.severity}</span>
              {w.synthetic && <span className="pl-chip pl-chip-synthetic">SYNTHETIC</span>}
              <span className="pl-small pl-muted">
                routed by <code>{w.routed_by}</code>
              </span>
            </div>
            {w.notified_personas.length > 0 && (
              <div className="pl-small pl-gap-top">
                <strong>Notified:</strong>{" "}
                {w.notified_personas.map((id) => names[id] ?? id).join(", ")}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="pl-small pl-muted pl-gap-top">
        {DELIVERY_NOTE}{" "}
        <Link to="/inbox" className="pl-link">
          Open inbox
        </Link>{" "}
        <span className="pl-chip pl-chip-grey" title="Demo workflow stored in ThermoMind only; nothing is sent to a CMMS">SIMULATED WORKFLOW · NOT A CMMS</span>
      </div>
    </section>
  );
}
