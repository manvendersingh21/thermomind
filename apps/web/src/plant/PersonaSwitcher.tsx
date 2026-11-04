import { useCallback, useEffect, useState } from "react";
import { getInbox, getPersonas } from "./api";
import { usePersona } from "./persona";
import type { Persona } from "./types";
import "./plant.css";

const POLL_MS = 15000;

export function PersonaSwitcher() {
  const [persona, setPersona] = usePersona();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [unread, setUnread] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const c = new AbortController();
    getPersonas(c.signal)
      .then((r) => {
        setPersonas(r.personas);
        setFailed(false);
      })
      .catch(() => {
        if (!c.signal.aborted) setFailed(true);
      });
    return () => c.abort();
  }, []);

  const poll = useCallback((signal?: AbortSignal) => {
    getInbox(undefined, signal)
      .then((r) => setUnread(r.unread_count))
      .catch(() => {
        if (!signal?.aborted) setUnread(null);
      });
  }, []);

  useEffect(() => {
    const c = new AbortController();
    setUnread(null);
    poll(c.signal);
    const t = window.setInterval(() => poll(c.signal), POLL_MS);
    const onRefresh = () => poll(c.signal);
    window.addEventListener("thermomind:inbox-changed", onRefresh);
    return () => {
      c.abort();
      window.clearInterval(t);
      window.removeEventListener("thermomind:inbox-changed", onRefresh);
    };
  }, [persona, poll]);

  const options = personas.length > 0 ? personas : [{ persona_id: persona, name: persona, role: "" } as Persona];

  return (
    <div className="pl-switcher" title="Demo account — no authentication. Selects whose inbox and work requests you see.">
      <label className="pl-switcher-label" htmlFor="pl-persona-select">
        Viewing as
      </label>
      <select
        id="pl-persona-select"
        className="pl-select"
        value={persona}
        onChange={(e) => setPersona(e.target.value)}
        aria-label="Switch demo persona"
      >
        {options.map((p) => (
          <option key={p.persona_id} value={p.persona_id}>
            {(p.role ? `${p.name} — ${p.role}` : p.name) + (p.external ? " (external)" : "")}
          </option>
        ))}
      </select>
      <span className="pl-chip pl-chip-blue">demo account</span>
      {options.find((p) => p.persona_id === persona)?.external && (
        <span className="pl-chip pl-chip-yellow">external</span>
      )}
      {unread !== null && unread > 0 && (
        <span className="pl-badge" aria-label={`${unread} unread notifications`}>
          {unread}
        </span>
      )}
      {failed && <span className="pl-muted pl-small">personas unavailable</span>}
    </div>
  );
}
