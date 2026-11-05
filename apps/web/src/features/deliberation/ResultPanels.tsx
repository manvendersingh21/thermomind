import { ArrowRight, ShieldCheck } from "lucide-react";
import { Fragment } from "react";
import type { ReactNode } from "react";
import { Chip, FindingChip, ProvenanceBadge, VERDICT_STYLE } from "./badges";
import type {
  Consensus,
  ConstraintFinding,
  ModelledChange,
  Outcome,
  Recommendation,
  Rehearsal,
  Verdict,
} from "./types";

export function PanelTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="panel-header">
      <h2 className="panel-title">{children}</h2>
      {right}
    </div>
  );
}

const fmt = (n: number, d = 3) => (Number.isInteger(n) ? String(n) : Number(n.toPrecision(d + 1)).toString());

// ---------------------------------------------------------------- modelled change
export function ChangePanel({ change }: { change: ModelledChange }) {
  return (
    <section className="panel" aria-label="Modelled change">
      <PanelTitle
        right={change.observable ? undefined : <Chip cls="border-dashed border-ink-500 bg-ink-800 text-ink-300">not observable in this data</Chip>}
      >
        Modelled change: {change.label}
      </PanelTitle>
      <div className="space-y-3 px-5 py-4">
        <p className="text-base text-ink-100">{change.text}</p>
        {change.deltas.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th scope="col">Measurement</th>
                  <th scope="col">Delta</th>
                  <th scope="col">Role</th>
                  <th scope="col">Basis</th>
                  <th scope="col">Provenance</th>
                  <th scope="col">Slope / r</th>
                </tr>
              </thead>
              <tbody>
                {change.deltas.map((d, i) => (
                  <tr key={`${d.measurement}-${i}`}>
                    <td className="font-mono font-semibold">{d.measurement}</td>
                    <td className="whitespace-nowrap font-mono">
                      {d.delta > 0 ? "+" : ""}
                      {fmt(d.delta)} {d.unit}
                    </td>
                    <td>
                      <Chip cls={d.role === "primary" ? "border-blue-300 bg-blue-50 text-blue-800" : "border-ink-600 bg-white text-ink-200"}>{d.role}</Chip>
                    </td>
                    <td className="text-sm">{d.basis}</td>
                    <td>
                      <ProvenanceBadge p={d.provenance} />
                    </td>
                    <td className="whitespace-nowrap font-mono text-sm">
                      {d.slope !== null ? `slope ${fmt(d.slope)}${d.slope_of ? ` per ${d.slope_of}` : ""}` : "n/a"}
                      {d.pearson_r !== null ? ` · r ${d.pearson_r.toFixed(2)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-ink-400">No quantitative measurement deltas for this change.</p>
        )}
        {change.qualitative_notes.length > 0 ? (
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-200">
            {change.qualitative_notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        ) : null}
        <p className="text-xs text-ink-400">{change.slope_label}</p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- constraint findings
export function FindingsPanel({ findings }: { findings: ConstraintFinding[] }) {
  return (
    <section className="panel" aria-label="Constraint findings">
      <PanelTitle>Constraint findings (deterministic pre-checks)</PanelTitle>
      {findings.length === 0 ? (
        <p className="px-5 py-4 text-sm text-ink-400">No findings yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Check</th>
                <th scope="col">Status</th>
                <th scope="col">Detail</th>
                <th scope="col">Provenance</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f) => (
                <tr key={`${f.n}-${f.key}`}>
                  <td className="font-mono">{f.n}</td>
                  <td className="font-semibold">{f.title}</td>
                  <td>
                    <FindingChip s={f.status} />
                  </td>
                  <td className="text-sm">{f.detail}</td>
                  <td>
                    <ProvenanceBadge p={f.provenance} />
                  </td>
                  <td className="font-mono text-xs text-ink-400">{f.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- recommendation
const REC: Record<Recommendation, { label: string; ring: string; chip: string }> = {
  proceed_with_conditions: { label: "Proceed, with conditions", ring: "border-green-500", chip: "border-green-300 bg-green-50 text-green-800" },
  do_not_proceed: { label: "Do not proceed", ring: "border-red-500", chip: "border-red-300 bg-red-50 text-red-800" },
  insufficient_evidence: { label: "Insufficient evidence", ring: "border-amber-500", chip: "border-amber-300 bg-amber-50 text-amber-900" },
};

function ConsensusBar({ c }: { c: Consensus }) {
  const parts: { key: Verdict; n: number; label: string }[] = [
    { key: "support", n: c.support, label: "support" },
    { key: "oppose", n: c.oppose, label: "oppose" },
    { key: "neutral", n: c.neutral, label: "neutral" },
    { key: "insufficient_evidence", n: c.insufficient, label: "insufficient evidence" },
  ];
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <div>
      <div
        role="img"
        aria-label={`Consensus: ${parts.map((p) => `${p.n} ${p.label}`).join(", ")}`}
        className="flex h-4 w-full overflow-hidden rounded-full border border-ink-600 bg-ink-800"
      >
        {total > 0
          ? parts
              .filter((p) => p.n > 0)
              .map((p) => <div key={p.key} className={VERDICT_STYLE[p.key].bar} style={{ width: `${(p.n / total) * 100}%` }} />)
          : null}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-100">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span className={`inline-block h-3 w-3 rounded-sm ${VERDICT_STYLE[p.key].bar}`} aria-hidden="true" />
            {p.label}: <b>{p.n}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SubHead({ children }: { children: ReactNode }) {
  return <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-300">{children}</h3>;
}

export function OutcomePanel({ outcome, personaLabel }: { outcome: Outcome; personaLabel: (id: string) => string }) {
  const r = REC[outcome.recommendation] ?? REC.insufficient_evidence;
  return (
    <section className={`panel border-2 ${r.ring}`} aria-label="Recommendation">
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck size={20} className="text-ink-300" aria-hidden="true" />
          <h2 className="text-lg font-bold text-ink-50">Recommendation</h2>
          <span className={`rounded-md border px-2.5 py-0.5 text-sm font-bold ${r.chip}`}>{r.label}</span>
          <Chip cls={outcome.source === "deterministic_fallback" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-800"}>
            {outcome.source_label || (outcome.source === "model" ? "model" : "deterministic fallback")}
          </Chip>
        </div>
        {outcome.summary ? <p className="mt-3 text-base text-ink-100">{outcome.summary}</p> : null}
        {outcome.guard_notes.length > 0 ? (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-amber-900">
            {outcome.guard_notes.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        ) : null}

        <div className="mt-4">
          <SubHead>Consensus among agents</SubHead>
          <ConsensusBar c={outcome.consensus} />
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {outcome.dissent.length > 0 ? (
            <div>
              <SubHead>Dissent</SubHead>
              <ul className="space-y-1 text-sm text-ink-100">
                {outcome.dissent.map((d, i) => (
                  <li key={i}>
                    <span className="font-semibold">{d.subsystem}:</span> {d.why}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {outcome.conditions.length > 0 ? (
            <div>
              <SubHead>Conditions</SubHead>
              <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink-100">
                {outcome.conditions.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        {outcome.what_could_go_wrong.length > 0 ? (
          <div className="mt-4">
            <SubHead>What could go wrong (domino)</SubHead>
            <ol className="flex flex-wrap items-stretch gap-y-2 text-sm text-ink-100">
              {outcome.what_could_go_wrong.map((s, i) => (
                <Fragment key={i}>
                  <li className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5">
                    <span className="mr-1.5 font-mono text-xs font-bold text-red-800">{i + 1}</span>
                    {s}
                  </li>
                  {i < outcome.what_could_go_wrong.length - 1 ? (
                    <li aria-hidden="true" className="flex items-center px-1.5 text-red-700">
                      <ArrowRight size={16} />
                    </li>
                  ) : null}
                </Fragment>
              ))}
            </ol>
          </div>
        ) : null}

        {outcome.rehearsal_suggestion ? (
          <div className="mt-4">
            <SubHead>Rehearsal suggestion</SubHead>
            <p className="text-sm text-ink-100">{outcome.rehearsal_suggestion}</p>
          </div>
        ) : null}

        {outcome.who_must_approve.length > 0 ? (
          <div className="mt-4">
            <SubHead>Who must approve</SubHead>
            <div className="flex flex-wrap gap-1.5">
              {outcome.who_must_approve.map((p) => (
                <Chip key={p} cls="border-ink-600 bg-white text-ink-100">
                  {personaLabel(p)}
                </Chip>
              ))}
            </div>
          </div>
        ) : null}

        <p className="mt-4 border-t border-ink-700 pt-3 text-xs text-ink-400">{outcome.disclaimer}</p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- rehearsal
export function RehearsalPanel({ r }: { r: Rehearsal }) {
  const ok = r.status === "available";
  return (
    <section className="panel" aria-label="Rehearsal">
      <PanelTitle right={<Chip cls={ok ? "border-green-300 bg-green-50 text-green-800" : "border-dashed border-ink-500 bg-ink-800 text-ink-300"}>{r.status}</Chip>}>
        Rehearsal (what-if on historical data)
      </PanelTitle>
      <div className="space-y-2 px-5 py-4 text-sm text-ink-100">
        {r.reason ? <p>{r.reason}</p> : null}
        {ok ? <p className="text-ink-300">Steps: <b className="font-mono">{r.steps}</b></p> : null}
        {r.outcome_summary ? <p>{r.outcome_summary}</p> : null}
      </div>
    </section>
  );
}
