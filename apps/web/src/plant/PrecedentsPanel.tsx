import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, getPrecedents } from "./api";
import type { PrecedentsResponse } from "./types";
import "./plant.css";

function decisionClass(d: string): string {
  if (d === "accepted") return "pl-chip-green";
  if (d === "rejected") return "pl-chip-red";
  return "pl-chip-yellow";
}

export function PrecedentsPanel({ caseId }: { caseId: string }) {
  const [data, setData] = useState<PrecedentsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError(null);
    getPrecedents(caseId, c.signal)
      .then((r) => {
        setData(r);
        setLoading(false);
      })
      .catch((e) => {
        if (c.signal.aborted) return;
        setError(errorMessage(e));
        setLoading(false);
      });
    return () => c.abort();
  }, [caseId]);

  return (
    <section className="pl-root pl-card" aria-label="Similar reviewed cases">
      <h2 className="pl-h2">Similar reviewed cases (precedents)</h2>
      {loading && <div className="pl-muted">Loading precedents…</div>}
      {error && (
        <div className="pl-alert pl-alert-err" role="alert">
          {error}
        </div>
      )}
      {data && (
        <>
          {data.precedents.length === 0 ? (
            <div className="pl-empty">
              No reviewed precedents yet — review decisions on the Investigation page become precedents.
            </div>
          ) : (
            <ul className="pl-stack pl-plain">
              {data.precedents.map((p) => (
                <li key={`${p.case_id}-${p.reviewed_at_utc}`} className="pl-subcard">
                  <div className="pl-row pl-wrap">
                    <Link to={`/investigations/${encodeURIComponent(p.case_id)}`} className="pl-link pl-strong">
                      {p.case_id}
                    </Link>
                    <span className={`pl-chip ${decisionClass(p.decision)}`}>{p.decision}</span>
                    {p.synthetic && <span className="pl-chip pl-chip-synthetic">SYNTHETIC</span>}
                    <span className="pl-chip pl-chip-blue">similarity {(p.similarity * 100).toFixed(0)}%</span>
                  </div>
                  <div className="pl-small">
                    {p.scenario_label}
                    {p.rank1_hypothesis ? (
                      <>
                        {" · rank-1 hypothesis: "}
                        <strong>{p.rank1_hypothesis}</strong>
                      </>
                    ) : null}
                  </div>
                  <div className="pl-small pl-muted">
                    reviewed by {p.reviewer} · {new Date(p.reviewed_at_utc).toLocaleString()}
                  </div>
                  {p.comment && <div className="pl-small">“{p.comment}”</div>}
                </li>
              ))}
            </ul>
          )}
          <p className="pl-small pl-muted">{data.note}</p>
          <p className="pl-small pl-muted">Reviewed cases considered: {data.reviewed_cases_considered}</p>
        </>
      )}
    </section>
  );
}
