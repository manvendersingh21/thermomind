import { CheckCircle2, CircleDashed, HelpCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { Assumption } from "../types";
import { fmtNum } from "../../../lib/format";

export function StatusBox({ status, reasons }: { status: string; reasons: string[] }) {
  const consider = status.startsWith("consider");
  const insufficient = status === "insufficient data";
  const cls = consider
    ? "border-yellow-400 bg-yellow-50 text-yellow-900"
    : insufficient
      ? "border-ink-600 bg-ink-800 text-ink-200"
      : "border-green-300 bg-green-50 text-green-900";
  const icon = consider ? <CheckCircle2 size={18} /> : insufficient ? <HelpCircle size={18} /> : <CircleDashed size={18} />;
  return (
    <div className={`rounded-lg border px-4 py-3 ${cls}`} role="status">
      <div className="flex items-center gap-2 font-semibold">
        {icon}
        <span className="uppercase tracking-wide">{status}</span>
      </div>
      {reasons.length ? (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-sm">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function Computation({ text }: { text: string }) {
  return (
    <details className="rounded-lg border border-ink-700 bg-ink-950 px-4 py-2.5" open>
      <summary className="cursor-pointer text-sm font-semibold text-ink-100">How this was computed</summary>
      <p className="mt-2 font-mono text-xs leading-relaxed text-ink-200">{text}</p>
    </details>
  );
}

export function AssumptionsEcho({ items, caveats }: { items: Assumption[]; caveats: string[] }) {
  return (
    <details className="rounded-lg border border-ink-700 px-4 py-2.5">
      <summary className="cursor-pointer text-sm font-semibold text-ink-100">Assumptions used &amp; caveats</summary>
      <table className="mt-2 w-full text-xs">
        <tbody>
          {items.map((a) => (
            <tr key={a.key} className="border-b border-ink-800 last:border-b-0">
              <td className="py-1 pr-2 text-ink-300">{a.label}</td>
              <td className="py-1 pr-2 text-right font-mono text-ink-50">
                {typeof a.value === "number" ? fmtNum(a.value, 3) : a.value}
              </td>
              <td className="py-1 pr-2 text-ink-400">{a.unit}</td>
              <td className="py-1 text-right">
                <span className={a.source === "user_input" ? "font-semibold text-yellow-800" : "text-ink-400"}>
                  {a.source === "user_input" ? "edited" : "default"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-ink-300">
        {caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </details>
  );
}

export function Kpi({ label, value, unit, caption, tone = "default" }: { label: string; value: ReactNode; unit?: string; caption?: ReactNode; tone?: "default" | "model" | "amber" }) {
  const accent = tone === "model" ? "border-t-green-500" : tone === "amber" ? "border-t-yellow-400" : "border-t-blue-600";
  return (
    <div className={`rounded-lg border border-ink-700 border-t-2 bg-white px-3 py-2.5 ${accent}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-ink-400">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="font-mono text-xl font-semibold tabular-nums text-ink-50">{value}</span>
        {unit ? <span className="text-xs text-ink-300">{unit}</span> : null}
      </div>
      {caption ? <div className="mt-0.5 text-xs text-ink-400">{caption}</div> : null}
    </div>
  );
}

/** Parse a string-backed numeric form into numbers; returns the first bad key or the parsed object. */
export function parseNumbers<T>(form: Record<keyof T, string>): { ok: true; value: T } | { ok: false; key: string } {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(form) as [string, string][]) {
    const n = Number(v);
    if (v.trim() === "" || !Number.isFinite(n)) return { ok: false, key: k };
    out[k] = n;
  }
  return { ok: true, value: out as T };
}
