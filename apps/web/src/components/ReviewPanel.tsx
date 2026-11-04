import { Check, FileQuestion, Lock, X } from "lucide-react";
import { useState } from "react";
import { submitReview } from "../api/client";
import type { Investigation, ReviewDecision } from "../api/types";
import { fmtDateTime } from "../lib/format";
import { ErrorBanner, Spinner } from "./Feedback";
import { ReviewedBadge } from "./SourceBadge";

interface Props {
  investigation: Investigation;
  onReviewed: (inv: Investigation) => void;
}

export function ReviewPanel({ investigation, onReviewed }: Props) {
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState("demo-engineer");
  const [busy, setBusy] = useState<ReviewDecision | null>(null);
  const [error, setError] = useState<unknown>(null);
  const review = investigation.review;
  const disabled = review !== null || busy !== null || investigation.status === "running" || investigation.status === "queued";

  async function decide(decision: ReviewDecision) {
    setBusy(decision);
    setError(null);
    try {
      const updated = await submitReview(investigation.case_id, {
        decision,
        reviewer: reviewer.trim() || "demo-engineer",
        comment: comment.trim() || null,
      });
      onReviewed(updated);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">Engineer review</div>
          <div className="mt-0.5 text-sm text-ink-300">Records a human decision on this draft. No plant control actions are possible from this software.</div>
        </div>
        {review ? <ReviewedBadge decision={review.decision} /> : <span className="text-sm font-semibold uppercase tracking-wide text-amber-800">Awaiting decision</span>}
      </div>
      <div className="px-5 py-4">
        {review ? (
          <div className="rounded-lg border border-green-300 bg-green-50 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-base">
              <span className="font-semibold text-ink-50">Decision: {review.decision.replace(/_/g, " ")}</span>
              <span className="text-ink-300">by {review.reviewer}</span>
              <span className="font-mono text-sm text-ink-400">{fmtDateTime(review.ts_utc)}</span>
            </div>
            {review.comment ? <p className="mt-2 text-base text-ink-100">“{review.comment}”</p> : <p className="mt-2 text-sm text-ink-400">No comment recorded.</p>}
            <div className="mt-3 flex items-center gap-1.5 text-sm text-ink-400">
              <Lock size={14} /> Review controls are disabled after a decision is recorded.
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-4 gap-4">
              <label className="col-span-1 flex flex-col gap-1.5">
                <span className="label">Reviewer</span>
                <input className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} disabled={disabled} />
              </label>
              <label className="col-span-3 flex flex-col gap-1.5">
                <span className="label">Comment (optional)</span>
                <textarea
                  className="input h-24 resize-y py-2"
                  placeholder="Engineering notes, follow-up actions to request, reasons for rejection…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  disabled={disabled}
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" className="btn-primary" onClick={() => decide("accepted")} disabled={disabled}>
                {busy === "accepted" ? <Spinner /> : <Check size={18} />} Accept for review record
              </button>
              <button type="button" className="btn-danger" onClick={() => decide("rejected")} disabled={disabled}>
                {busy === "rejected" ? <Spinner /> : <X size={18} />} Reject
              </button>
              <button type="button" className="btn-amber" onClick={() => decide("more_data_requested")} disabled={disabled}>
                {busy === "more_data_requested" ? <Spinner /> : <FileQuestion size={18} />} Request more data
              </button>
            </div>
            {error ? <ErrorBanner className="mt-4" title="Could not record review" error={error} /> : null}
          </>
        )}
      </div>
    </div>
  );
}
