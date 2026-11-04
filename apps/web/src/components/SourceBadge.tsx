import { Bot, CheckCircle2, Database, FlaskConical, ShieldAlert, Sigma, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

export type SourceBadgeVariant = "real" | "synthetic" | "model" | "review" | "meta" | "offline";

const STYLES: Record<SourceBadgeVariant, { cls: string; icon: ReactNode; defaultLabel: string }> = {
  real: {
    cls: "border-green-300 bg-green-50 text-green-800",
    icon: <Database size={14} strokeWidth={2.2} />,
    defaultLabel: "REAL PUBLIC DATA",
  },
  synthetic: {
    cls: "border-yellow-400 bg-yellow-100 text-yellow-900",
    icon: <FlaskConical size={14} strokeWidth={2.2} />,
    defaultLabel: "SYNTHETIC OVERLAY",
  },
  model: {
    cls: "border-dashed border-green-400 bg-white text-green-800",
    icon: <Sigma size={14} strokeWidth={2.2} />,
    defaultLabel: "MODEL-DERIVED",
  },
  review: {
    cls: "border-yellow-400 bg-yellow-100 text-yellow-900",
    icon: <ShieldAlert size={14} strokeWidth={2.2} />,
    defaultLabel: "DRAFT — HUMAN REVIEW REQUIRED",
  },
  meta: {
    cls: "border-blue-300 bg-blue-50 text-blue-800",
    icon: <Bot size={14} strokeWidth={2.2} />,
    defaultLabel: "META LIVE",
  },
  offline: {
    cls: "border-ink-600 bg-ink-800 text-ink-200",
    icon: <WifiOff size={14} strokeWidth={2.2} />,
    defaultLabel: "OFFLINE PREVIEW",
  },
};

interface Props {
  variant: SourceBadgeVariant;
  label?: string;
  title?: string;
  size?: "sm" | "md";
  className?: string;
}

export function SourceBadge({ variant, label, title, size = "md", className = "" }: Props) {
  const s = STYLES[variant];
  const sizing = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-md border font-semibold sm:whitespace-nowrap tracking-wide ${sizing} ${s.cls} ${className}`}
    >
      {s.icon}
      {label ?? s.defaultLabel}
    </span>
  );
}

export function ReviewedBadge({ decision }: { decision: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-green-300 bg-green-50 px-2.5 py-1 text-sm font-semibold tracking-wide text-green-800">
      <CheckCircle2 size={14} strokeWidth={2.2} />
      REVIEWED · {decision.replace(/_/g, " ").toUpperCase()}
    </span>
  );
}
