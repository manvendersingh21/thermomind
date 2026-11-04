import { AlertTriangle, CheckCircle2, Flag, X, XCircle } from "lucide-react";
import { useEffect } from "react";
import type { Evidence } from "../api/types";
import { fmtNum, fmtPct, fmtSigned, humanize, rangeLabel } from "../lib/format";
import { SourceBadge } from "./SourceBadge";

interface Props {
  evidence: Evidence | null;
  missingId?: string | null;
  onClose: () => void;
}

function kindBadge(kind: Evidence["kind"]) {
  switch (kind) {
    case "real_observation":
      return <SourceBadge variant="real" label="REAL OBSERVATION" size="sm" />;
    case "model_derived":
      return <SourceBadge variant="model" label="MODEL-DERIVED" size="sm" />;
    case "synthetic_overlay":
      return <SourceBadge variant="synthetic" label="SYNTHETIC OVERLAY" size="sm" />;
    case "measured_plus_synthetic_overlay":
      return <SourceBadge variant="synthetic" label="MEASURED + SYNTHETIC OVERLAY" size="sm" />;
  }
}

function dq(level: Evidence["data_quality"]) {
  if (level === "pass")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-green-300 bg-green-50 px-2 py-0.5 text-sm font-semibold text-green-800">
        <CheckCircle2 size={14} /> PASS
      </span>
    );
  if (level === "warn")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-400 bg-yellow-100 px-2 py-0.5 text-sm font-semibold text-amber-800">
        <AlertTriangle size={14} /> WARN
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-red-300 bg-red-50 px-2 py-0.5 text-sm font-semibold text-red-800">
      <XCircle size={14} /> FAIL — data quality
    </span>
  );
}

function Row({ k, v, mono = false }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-5 gap-3 border-b border-ink-700/60 py-2.5 text-base">
      <div className="col-span-2 text-ink-300">{k}</div>
      <div className={`col-span-3 break-words text-ink-50 ${mono ? "font-mono" : ""}`}>{v}</div>
    </div>
  );
}

export function EvidenceDrawer({ evidence, missingId, onClose }: Props) {
  const open = evidence !== null || !!missingId;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-slate-900/30 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`fixed right-0 top-0 z-50 flex h-full w-[520px] max-w-full flex-col border-l border-ink-600 bg-ink-850 shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        role="dialog"
        aria-label="Evidence detail"
      >
        <div className="flex items-start justify-between gap-3 border-b border-ink-700 px-5 py-4">
          <div className="min-w-0">
            <div className="label">Evidence</div>
            <div className="mt-0.5 font-mono text-lg font-semibold text-blue-700">{evidence?.evidence_id ?? missingId}</div>
          </div>
          <button type="button" onClick={onClose} className="btn-secondary h-9 w-9 px-0" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {!evidence && missingId ? (
            <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900">
              The report cites <span className="font-mono">{missingId}</span>, but this id is not among the evidence returned by the
              deterministic tools for this case. Treat the citation as unverified.
            </div>
          ) : null}
          {evidence ? (
            <>
              <div className="mb-3 flex flex-wrap gap-2">
                {kindBadge(evidence.kind)}
                {evidence.is_synthetic ? <SourceBadge variant="synthetic" label="SYNTHETIC = TRUE" size="sm" /> : <SourceBadge variant="real" label="SYNTHETIC = FALSE" size="sm" />}
                {evidence.model_version ? <SourceBadge variant="model" label={evidence.model_version} size="sm" /> : null}
                {dq(evidence.data_quality)}
              </div>
              <h3 className="text-xl font-semibold text-ink-50">{evidence.title}</h3>
              <div className="mt-1 text-base text-ink-300">
                metric <span className="font-mono text-ink-100">{evidence.metric}</span> · unit{" "}
                <span className="font-mono text-ink-100">{evidence.unit || "—"}</span>
              </div>

              <div className="mt-4">
                <Row k="Sample range (window)" v={rangeLabel(evidence.sample_range)} mono />
                <Row k="Reference range" v={evidence.reference_range ? rangeLabel(evidence.reference_range) : "— (no reference)"} mono />
                <Row k="Observed statistic" v={`${fmtNum(evidence.observed_stat, 3)} ${evidence.unit}`} mono />
                <Row k="Comparison statistic" v={`${fmtNum(evidence.comparison_stat, 3)} ${evidence.unit}`} mono />
                <Row k="Delta" v={`${fmtSigned(evidence.delta, 3)} ${evidence.unit}`} mono />
                <Row k="Delta %" v={fmtPct(evidence.delta_pct, 2)} mono />
                <Row k="z-score" v={fmtNum(evidence.z_score, 2)} mono />
                <Row k="Method" v={humanize(evidence.method)} />
              </div>

              <div className="mt-4">
                <div className="label mb-1.5">Computation</div>
                <pre className="whitespace-pre-wrap break-words rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 font-mono text-sm leading-relaxed text-ink-100">
                  {evidence.computation}
                </pre>
              </div>

              {evidence.flags.length > 0 ? (
                <div className="mt-4">
                  <div className="label mb-1.5">Flags</div>
                  <div className="flex flex-wrap gap-1.5">
                    {evidence.flags.map((f) => (
                      <span key={f} className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 font-mono text-sm text-amber-800">
                        <Flag size={12} /> {f}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}

              {Object.keys(evidence.values).length > 0 ? (
                <div className="mt-4">
                  <div className="label mb-1.5">Values used</div>
                  <div className="rounded-lg border border-ink-700 bg-ink-950">
                    {Object.entries(evidence.values).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-3 border-b border-ink-800 px-3 py-1.5 font-mono text-sm last:border-b-0">
                        <span className="text-ink-300">{k}</span>
                        <span className="text-ink-100">{typeof v === "number" ? fmtNum(v, 4) : JSON.stringify(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-5 text-sm text-ink-400">
                case <span className="font-mono">{evidence.case_id}</span>. Evidence is computed deterministically from the rows; sample
                positions are ordered hourly indices — the dataset has no timestamps.
              </div>
            </>
          ) : null}
        </div>
      </aside>
    </>
  );
}
