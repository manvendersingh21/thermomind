import { AlertTriangle, Database, Loader2, RefreshCw, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { errorMessage, isApiError } from "../api/client";

export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

export function PanelSkeleton({ lines = 4, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`panel p-5 ${className}`}>
      <Skeleton className="mb-4 h-5 w-1/3" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={`mb-3 h-4 ${i % 3 === 2 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div className="panel p-5">
      <Skeleton className="mb-4 h-5 w-48" />
      <Skeleton style={{ height }} className="w-full" />
    </div>
  );
}

interface ErrorBannerProps {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorBanner({ error, title = "Request failed", onRetry, className = "" }: ErrorBannerProps) {
  const status = isApiError(error) ? error.status : null;
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-red-900 ${className}`}
    >
      <XCircle size={20} className="mt-0.5 shrink-0 text-red-700" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">
          {title}
          {status ? <span className="ml-2 font-mono text-sm text-red-700">HTTP {status}</span> : null}
        </div>
        <div className="mt-0.5 break-words text-base text-red-900">{errorMessage(error)}</div>
      </div>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="btn-secondary h-9 shrink-0 px-3 text-sm">
          <RefreshCw size={14} /> Retry
        </button>
      ) : null}
    </div>
  );
}

export function WarnBanner({ children, className = "", icon }: { children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <div className={`flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-amber-900 ${className}`}>
      <span className="mt-0.5 shrink-0 text-amber-700">{icon ?? <AlertTriangle size={20} />}</span>
      <div className="min-w-0 flex-1 text-base">{children}</div>
    </div>
  );
}

export function InfoBanner({ children, className = "", icon }: { children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <div className={`flex items-start gap-3 rounded-xl border border-ink-600 bg-ink-800/70 px-4 py-3 text-ink-100 ${className}`}>
      {icon ? <span className="mt-0.5 shrink-0 text-ink-300">{icon}</span> : null}
      <div className="min-w-0 flex-1 text-base">{children}</div>
    </div>
  );
}

export function EmptyDataset({ className = "" }: { className?: string }) {
  return (
    <div className={`panel flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${className}`}>
      <Database size={32} className="text-ink-400" />
      <div className="text-lg font-semibold text-ink-100">No dataset loaded</div>
      <p className="max-w-lg text-base text-ink-300">
        The UCI Gas Turbine dataset has not been fetched yet. From the repository root run{" "}
        <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-blue-700">make data</code> then{" "}
        <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-blue-700">make train</code>, and restart the
        API (or POST <code className="font-mono text-ink-200">/api/datasets/seed-uci</code>).
      </p>
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 size={18} className={`animate-spin ${className}`} />;
}
