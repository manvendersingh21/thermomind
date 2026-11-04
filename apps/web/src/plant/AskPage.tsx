import { useEffect, useState } from "react";
import { errorMessage, listInvestigationsForPicker, listWhatIf } from "./api";
import type { Investigation } from "../api/types";
import type { WhatIfSession } from "./types";
import { WhatIfConsole, WhatIfResult } from "./WhatIfConsole";
import { DominoMap } from "../features/collab/DominoMap";
import "./plant.css";

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function AskPage() {
  const [cases, setCases] = useState<Investigation[]>([]);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [caseId, setCaseId] = useState<string>("");
  const [recent, setRecent] = useState<WhatIfSession[]>([]);
  const [recentError, setRecentError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    listInvestigationsForPicker(c.signal)
      .then(setCases)
      .catch((e) => {
        if (!c.signal.aborted) setCasesError(errorMessage(e));
      });
    return () => c.abort();
  }, []);

  useEffect(() => {
    const c = new AbortController();
    const load = () =>
      listWhatIf(20, c.signal)
        .then((r) => {
          setRecent(r);
          setRecentError(null);
        })
        .catch((e) => {
          if (!c.signal.aborted) setRecentError(errorMessage(e));
        });
    load();
    const t = window.setInterval(load, 10000);
    return () => {
      c.abort();
      window.clearInterval(t);
    };
  }, []);

  return (
    <div className="pl-root pl-page">
      <header className="pl-page-head">
        <h1 className="pl-h1">Ask the plant</h1>
        <p className="pl-sub pl-muted">
          Pose a what-if on one measurement. Deterministic sensitivity tools compute the numbers; subsystem agents explain
          them.
        </p>
      </header>

      <div className="pl-card">
        <label className="pl-field">
          <span className="pl-label">Base case (optional)</span>
          <select className="pl-select" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
            <option value="">None — default 2014 window, rows [1200, 1320)</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} — {c.scenario.title}
                {c.scenario.synthetic ? " (SYNTHETIC)" : ""}
              </option>
            ))}
          </select>
        </label>
        {casesError && <div className="pl-small pl-muted">Case list unavailable: {casesError}</div>}
      </div>

      <WhatIfConsole caseId={caseId || undefined} />

      <DominoMap caseId={caseId || undefined} />

      <section>
        <h2 className="pl-h2">Recent what-if sessions</h2>
        {recentError && <div className="pl-alert pl-alert-err">{recentError}</div>}
        {recent.length === 0 && !recentError && <div className="pl-empty">No sessions yet.</div>}
        <ul className="pl-stack pl-plain">
          {recent.map((s) => {
            const open = openId === s.session_id;
            return (
              <li key={s.session_id} className="pl-card">
                <button className="pl-linkbtn" onClick={() => setOpenId(open ? null : s.session_id)} aria-expanded={open}>
                  <strong>
                    {s.request.measurement} {s.request.delta > 0 ? "+" : ""}
                    {s.request.delta}
                  </strong>{" "}
                  <span className="pl-chip pl-chip-blue pl-chip-sm">{s.status}</span>{" "}
                  <span className={`pl-chip pl-chip-sm ${s.mode === "meta_live" ? "pl-chip-green" : "pl-chip-grey"}`}>
                    {s.mode === "meta_live" ? "meta_live" : "offline"}
                  </span>
                </button>
                <div className="pl-small pl-muted">
                  {fmtTs(s.created_at_utc)} · persona {s.persona}
                  {s.request.case_id ? ` · case ${s.request.case_id}` : ""}
                  {s.request.question ? ` · “${s.request.question}”` : ""}
                </div>
                {open && (
                  <div className="pl-gap-top">
                    <WhatIfResult session={s} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
