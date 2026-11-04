import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, getInbox, getPersonas, markNotificationRead, updateWorkRequestStatus } from "./api";
import { usePersona } from "./persona";
import type { InboxResponse, Notification, Persona, WorkRequest, WorkRequestStatus } from "./types";
import { DELIVERY_NOTE } from "./types";
import "./plant.css";

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function sevClass(sev: string): string {
  const s = sev.toLowerCase();
  if (s === "high" || s === "critical" || s === "urgent") return "pl-chip-red";
  if (s === "medium" || s === "moderate") return "pl-chip-yellow";
  return "pl-chip-green";
}

function statusClass(s: WorkRequestStatus): string {
  if (s === "open") return "pl-chip-yellow";
  if (s === "acknowledged") return "pl-chip-blue";
  if (s === "done") return "pl-chip-green";
  return "pl-chip-grey";
}

type MyRole = "assignee" | "supervisor" | "cc" | "notified";

function myRole(wr: WorkRequest, persona: string): MyRole {
  if (wr.assigned_persona === persona) return "assignee";
  if (wr.supervisor_persona === persona) return "supervisor";
  if (wr.cc_personas.includes(persona)) return "cc";
  return "notified";
}

function WorkRequestCard({
  wr,
  persona,
  names,
  onChanged,
}: {
  wr: WorkRequest;
  persona: string;
  names: Record<string, string>;
  onChanged: (w: WorkRequest) => void;
}) {
  const role = myRole(wr, persona);
  const canAct = role === "assignee" || role === "supervisor";
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const act = async (status: Exclude<WorkRequestStatus, "open">) => {
    setBusy(true);
    setErr(null);
    try {
      const updated = await updateWorkRequestStatus(wr.id, status, comment);
      setComment("");
      onChanged(updated);
    } catch (e) {
      const m = errorMessage(e);
      const status409 = typeof e === "object" && e !== null && (e as { status?: number }).status === 409;
      setErr(status409 ? `Transition not allowed (it may have been updated elsewhere): ${m}. Refreshing.` : m);
      if (status409) window.dispatchEvent(new CustomEvent("thermomind:inbox-refresh"));
    } finally {
      setBusy(false);
    }
  };

  const final = wr.status === "done" || wr.status === "dismissed";
  return (
    <article className="pl-card pl-wr">
      <div className="pl-row pl-wrap">
        <h3 className="pl-card-title">{wr.title}</h3>
        <span className={`pl-chip ${statusClass(wr.status)}`}>{wr.status}</span>
        <span className={`pl-chip ${sevClass(wr.severity)}`}>severity: {wr.severity}</span>
        {wr.synthetic && <span className="pl-chip pl-chip-synthetic">SYNTHETIC</span>}
        <span className="pl-chip pl-chip-blue">you are: {role}</span>
      </div>
      {wr.assignment_label && <div className="pl-assign">{wr.assignment_label}</div>}
      <div className="pl-meta pl-small">
        <span>
          routed by <code>{wr.routed_by}</code>
        </span>
        <span>
          case{" "}
          <Link to={`/investigations/${encodeURIComponent(wr.case_id)}`} className="pl-link">
            {wr.case_id}
          </Link>
        </span>
        <span>{wr.scenario_label}</span>
        <span>created {fmtTs(wr.created_at_utc)}</span>
      </div>

      {wr.notified_personas.length > 0 && (
        <div className="pl-section">
          <div className="pl-h4">Notified (simulated in-app)</div>
          <ul className="pl-reasons">
            {wr.notified_personas.map((id) => (
              <li key={id}>
                <strong>{names[id] ?? id}</strong>
                {wr.notification_reasons[id] ? <span className="pl-muted"> — {wr.notification_reasons[id]}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {wr.checks.length > 0 && (
        <div className="pl-section">
          <div className="pl-h4">Checks for engineer review</div>
          <ul className="pl-list">
            {wr.checks.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {wr.history.length > 0 && (
        <div className="pl-section">
          <div className="pl-h4">History</div>
          <ul className="pl-history">
            {wr.history.map((h, i) => (
              <li key={i}>
                <span className="pl-muted">{fmtTs(h.ts_utc)}</span> · <strong>{h.persona}</strong> → {h.status}
                {h.comment ? <span> — “{h.comment}”</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!final && !canAct ? (
        <div className="pl-small pl-muted pl-gap-top">
          You are {role === "cc" ? "copied (cc)" : "notified"} on this request; only the assignee or supervisor can change its status.
        </div>
      ) : !final ? (
        <div className="pl-section">
          <input
            className="pl-input"
            type="text"
            placeholder="Optional comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={busy}
            aria-label="Comment"
          />
          <div className="pl-row pl-wrap pl-gap-top">
            {wr.status === "open" && (
              <button className="pl-btn pl-btn-blue" disabled={busy} onClick={() => act("acknowledged")}>
                Acknowledge
              </button>
            )}
            <button className="pl-btn pl-btn-green" disabled={busy} onClick={() => act("done")}>
              Done
            </button>
            <button className="pl-btn pl-btn-ghost" disabled={busy} onClick={() => act("dismissed")}>
              Dismiss
            </button>
            <span className="pl-chip pl-chip-grey" title="Demo workflow stored in ThermoMind only; nothing is sent to a CMMS">SIMULATED WORKFLOW · NOT A CMMS</span>
          </div>
        </div>
      ) : (
        <div className="pl-small pl-muted pl-gap-top">Final state — no further transitions.</div>
      )}
      {err && (
        <div className="pl-alert pl-alert-warn" role="alert">
          {err}
        </div>
      )}
    </article>
  );
}

export function InboxPage() {
  const [persona] = usePersona();
  const [inbox, setInbox] = useState<InboxResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    const c = new AbortController();
    getPersonas(c.signal)
      .then((r) => setNames(Object.fromEntries(r.personas.map((p: Persona) => [p.persona_id, `${p.name}${p.external ? " (external)" : ""}`]))))
      .catch(() => undefined);
    return () => c.abort();
  }, []);

  const load = useCallback(
    (signal?: AbortSignal) => {
      getInbox(persona, signal)
        .then((r) => {
          setInbox(r);
          setError(null);
          setLoading(false);
        })
        .catch((e) => {
          if (signal?.aborted) return;
          setError(errorMessage(e));
          setLoading(false);
        });
    },
    [persona],
  );

  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setInbox(null);
    load(c.signal);
    const onRefresh = () => load(c.signal);
    window.addEventListener("thermomind:inbox-refresh", onRefresh);
    return () => {
      c.abort();
      window.removeEventListener("thermomind:inbox-refresh", onRefresh);
    };
  }, [load]);

  const markRead = async (n: Notification) => {
    try {
      const upd = await markNotificationRead(n.id);
      setInbox((cur) =>
        cur
          ? {
              ...cur,
              notifications: cur.notifications.map((x) => (x.id === upd.id ? upd : x)),
              unread_count: Math.max(0, cur.unread_count - (n.read ? 0 : 1)),
            }
          : cur,
      );
      window.dispatchEvent(new CustomEvent("thermomind:inbox-changed"));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const onWrChanged = (w: WorkRequest) => {
    setInbox((cur) => (cur ? { ...cur, work_requests: cur.work_requests.map((x) => (x.id === w.id ? w : x)) } : cur));
    window.dispatchEvent(new CustomEvent("thermomind:inbox-changed"));
    load();
  };

  return (
    <div className="pl-root pl-page">
      <div className="pl-banner pl-banner-yellow" role="note">
        <strong>{DELIVERY_NOTE}</strong>
      </div>

      <header className="pl-page-head">
        <h1 className="pl-h1">Inbox</h1>
        {inbox ? (
          <p className="pl-sub">
            <strong>{inbox.persona.name}</strong> — {inbox.persona.role}{" "}
            <span className="pl-chip pl-chip-blue">demo account</span>
            {inbox.persona.external && <span className="pl-chip pl-chip-yellow">external</span>}
            <br />
            <span className="pl-muted">{inbox.persona.description}</span>
            <br />
            <span className="pl-muted pl-small">
              {inbox.unread_count} unread · {inbox.open_count} open work request{inbox.open_count === 1 ? "" : "s"}
            </span>
          </p>
        ) : (
          <p className="pl-sub pl-muted">Persona: {persona}</p>
        )}
      </header>

      {loading && <div className="pl-muted">Loading inbox…</div>}
      {error && (
        <div className="pl-alert pl-alert-err" role="alert">
          {error}
        </div>
      )}

      {inbox && (
        <>
          <section>
            <h2 className="pl-h2">Notifications</h2>
            {inbox.notifications.length === 0 ? (
              <div className="pl-empty">No notifications for this persona.</div>
            ) : (
              <ul className="pl-notifs">
                {inbox.notifications.map((n) => (
                  <li key={n.id} className={`pl-notif ${n.read ? "" : "pl-notif-unread"}`}>
                    <div className="pl-notif-body">
                      <div>{n.message}</div>
                      <div className="pl-small pl-muted">
                        {fmtTs(n.created_at_utc)} · {n.kind}
                        {n.case_id && (
                          <>
                            {" · "}
                            <Link to={`/investigations/${encodeURIComponent(n.case_id)}`} className="pl-link">
                              {n.case_id}
                            </Link>
                          </>
                        )}
                      </div>
                    </div>
                    {!n.read ? (
                      <button className="pl-btn pl-btn-ghost pl-btn-sm" onClick={() => markRead(n)}>
                        Mark read
                      </button>
                    ) : (
                      <span className="pl-small pl-muted">read</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="pl-h2">Work requests</h2>
            {inbox.work_requests.length === 0 ? (
              <div className="pl-empty">No work requests assigned to this persona.</div>
            ) : (
              <div className="pl-stack">
                {inbox.work_requests.map((w) => (
                  <WorkRequestCard key={w.id} wr={w} persona={persona} names={names} onChanged={onWrChanged} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
