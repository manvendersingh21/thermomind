import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../api/client";
import { getCaseActivity } from "./api";
import type { ActivityItem, ActivityResponse, ActorKind } from "./types";
import "../../plant/plant.css";
import "./collab.css";

type Filter = "all" | ActorKind;

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "agent", label: "Agents" },
  { id: "persona", label: "People (roles)" },
  { id: "human", label: "Reviewers" },
  { id: "system", label: "System" },
];

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function actorChip(item: ActivityItem): { cls: string; tag: string } {
  if (item.actor_kind === "agent") return { cls: "cb-tag-agent", tag: "AGENT" };
  if (item.actor_kind === "system") return { cls: "cb-tag-system", tag: "SYSTEM" };
  return { cls: "cb-tag-human", tag: "HUMAN" };
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

export function CaseActivityFeed({ caseId }: { caseId: string }) {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError(null);
    getCaseActivity(caseId, c.signal)
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

  const items = useMemo(
    () => (data?.items ?? []).filter((i) => filter === "all" || i.actor_kind === filter),
    [data, filter],
  );
  const unavailable = data ? Object.entries(data.sources).filter(([, ok]) => !ok).map(([k]) => k) : [];

  return (
    <section className="cb-root cb-section" aria-label="Case activity">
      <h2 className="cb-h2">Case activity — one shared record for every team</h2>
      <p className="cb-muted cb-small" style={{ margin: "0 0 8px" }}>
        Everything that happened on this case, in time order, with who or what did it. Agent entries are read-only
        legwork (analysis, routing, drafts); decisions are always made by people.
      </p>
      <div className="cb-row" role="group" aria-label="Filter activity by actor type" style={{ marginBottom: 6 }}>
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className="cb-chipbtn" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>

      {loading && <div className="cb-muted" role="status">Loading activity…</div>}
      {error && (
        <div className="pl-alert pl-alert-err" role="alert">
          {error}
        </div>
      )}
      {data && items.length === 0 && !loading ? (
        <div className="pl-empty">{data.items.length === 0 ? "No activity recorded for this case yet." : "No entries for this filter."}</div>
      ) : null}

      {items.length > 0 ? (
        <ol className="cb-timeline cb-plain" style={{ paddingLeft: 18 }}>
          {items.map((it, i) => {
            const chip = actorChip(it);
            return (
              <li key={`${it.ts_utc}-${i}`} className={`cb-tl-item cb-${it.actor_kind === "agent" ? "agent" : it.actor_kind === "system" ? "system" : "human"}`}>
                <div className="cb-row cb-small">
                  <span className="cb-muted">{fmtTs(it.ts_utc)}</span>
                  <span className={`cb-tag ${chip.cls}`}>{chip.tag}</span>
                  <strong>{it.actor.replace(/^agent:/, "")}</strong>
                  <span className="pl-chip pl-chip-grey pl-chip-sm">{kindLabel(it.kind)}</span>
                </div>
                <div>
                  {it.summary}
                  {it.link ? (
                    <>
                      {" "}
                      {it.link.startsWith("/") ? (
                        <Link to={it.link} className="cb-link cb-small">
                          Open
                        </Link>
                      ) : (
                        <a href={it.link} className="cb-link cb-small" target="_blank" rel="noreferrer">
                          Open
                        </a>
                      )}
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}

      {data?.note ? <p className="cb-small cb-muted" style={{ margin: "10px 0 0" }}>{data.note}</p> : null}
      {unavailable.length ? (
        <p className="cb-small cb-muted" style={{ margin: "4px 0 0" }}>Not available for this case: {unavailable.join(", ")}.</p>
      ) : null}
    </section>
  );
}

export default CaseActivityFeed;
