import type { ReactNode } from "react";
import { Skeleton } from "./Feedback";

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  caption?: ReactNode;
  icon?: ReactNode;
  loading?: boolean;
  tone?: "default" | "model" | "amber";
}

export function KpiCard({ label, value, unit, caption, icon, loading, tone = "default" }: Props) {
  const accent =
    tone === "model" ? "border-t-green-500" : tone === "amber" ? "border-t-yellow-400" : "border-t-blue-600";
  return (
    <div className={`panel border-t-2 px-5 py-4 ${accent}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="label">{label}</div>
        {icon ? <span className="text-ink-400">{icon}</span> : null}
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-9 w-28" />
      ) : (
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-mono text-3xl font-semibold tabular-nums text-ink-50">{value}</span>
          {unit ? <span className="text-base text-ink-300">{unit}</span> : null}
        </div>
      )}
      {caption ? <div className="mt-1.5 text-sm text-ink-300">{caption}</div> : null}
    </div>
  );
}
