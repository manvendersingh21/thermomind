import { ChevronLeft, ChevronRight, Compass, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listInvestigations } from "../../api/client";
import type { Investigation } from "../../api/types";
import { TOUR_STEPS } from "./tourSteps";
import type { TourStep } from "./tourSteps";

const STORAGE_KEY = "thermomind.tour.v1";
export const OPEN_TOUR_EVENT = "thermomind:open-tour";

interface Persisted {
  step: number;
  open: boolean;
  hidden: boolean;
}

function load(): Persisted {
  const base: Persisted = { step: 0, open: false, hidden: false };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const p = JSON.parse(raw) as Partial<Persisted>;
    const step = typeof p.step === "number" ? Math.min(Math.max(0, Math.floor(p.step)), TOUR_STEPS.length - 1) : 0;
    return { step, open: p.open === true, hidden: p.hidden === true };
  } catch {
    return base;
  }
}

function save(p: Persisted) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable: tour still works for this session */
  }
}

function newestFirst(a: Investigation, b: Investigation): number {
  return b.created_at_utc.localeCompare(a.created_at_utc);
}

/** Newest meta_live case for the scenario; falls back to any newest case of that scenario. */
function pickCase(list: Investigation[], scenario: string): Investigation | null {
  const mine = list.filter((i) => i.scenario?.scenario_id === scenario || i.request?.scenario_id === scenario).sort(newestFirst);
  return mine.find((i) => i.mode === "meta_live") ?? mine[0] ?? null;
}

export default function GuidedTour() {
  const navigate = useNavigate();
  const [state, setState] = useState<Persisted>(load);
  const [cases, setCases] = useState<Investigation[] | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);

  const update = useCallback((patch: Partial<Persisted>) => {
    setState((s) => {
      const next = { ...s, ...patch };
      save(next);
      return next;
    });
  }, []);

  // Allow re-opening after "Hide tour" via window.dispatchEvent(new Event("thermomind:open-tour")).
  useEffect(() => {
    const onOpen = () => update({ open: true, hidden: false });
    window.addEventListener(OPEN_TOUR_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_TOUR_EVENT, onOpen);
  }, [update]);

  // Fetch cases only while the tour is open.
  useEffect(() => {
    if (!state.open) return;
    const controller = new AbortController();
    listInvestigations(controller.signal)
      .then(setCases)
      .catch(() => {
        if (!controller.signal.aborted) setCases([]);
      });
    return () => controller.abort();
  }, [state.open]);

  // Focus management.
  useEffect(() => {
    if (state.open) {
      panelRef.current?.focus();
      wasOpen.current = true;
    } else if (wasOpen.current) {
      wasOpen.current = false;
      launcherRef.current?.focus();
    }
  }, [state.open]);

  const step: TourStep = TOUR_STEPS[state.step] ?? TOUR_STEPS[0]!;
  const last = state.step === TOUR_STEPS.length - 1;

  let goTo = "/";
  let unresolved = false;
  if (step.target.kind === "route") {
    goTo = step.target.to;
  } else {
    const found = cases ? pickCase(cases, step.target.scenario) : null;
    if (found) goTo = `/investigations/${encodeURIComponent(found.case_id)}`;
    else {
      goTo = step.target.fallback;
      unresolved = cases !== null;
    }
  }
  const resolvedCase =
    step.target.kind === "case" && cases ? pickCase(cases, step.target.scenario) : null;

  const close = () => update({ open: false });
  const go = (delta: number) => update({ step: Math.min(Math.max(state.step + delta, 0), TOUR_STEPS.length - 1) });

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    } else if (e.key === "ArrowRight" && !last) {
      go(1);
    } else if (e.key === "ArrowLeft" && state.step > 0) {
      go(-1);
    }
  };

  if (state.hidden) return null;

  if (!state.open) {
    return (
      <button
        ref={launcherRef}
        type="button"
        onClick={() => update({ open: true })}
        className="fixed top-3 right-4 z-50 inline-flex h-9 opacity-90 hover:opacity-100 items-center gap-2 rounded-full border border-yellow-400 bg-yellow-100 px-4 text-sm font-semibold text-yellow-900 shadow-lg transition hover:bg-yellow-200 focus:outline-none focus:ring-2 focus:ring-blue-300 print:hidden"
      >
        <Compass size={16} aria-hidden="true" />
        Judge tour
      </button>
    );
  }

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby="tm-tour-title"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="fixed top-14 right-4 z-50 w-[22rem] max-w-[calc(100vw-2.5rem)] rounded-xl border border-slate-300 bg-white p-4 text-slate-900 shadow-2xl focus:outline-none print:hidden"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Judge tour &middot; step {state.step + 1} of {TOUR_STEPS.length}
          </div>
          <h2 id="tm-tour-title" className="mt-0.5 text-lg font-semibold">
            {step.title}
          </h2>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label="Close tour"
          className="rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-300"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      <div
        className="mb-3 flex gap-1"
        role="progressbar"
        aria-valuemin={1}
        aria-valuemax={TOUR_STEPS.length}
        aria-valuenow={state.step + 1}
        aria-label="Tour progress"
      >
        {TOUR_STEPS.map((s, i) => (
          <span
            key={s.id}
            className={`h-1.5 flex-1 rounded-full ${i < state.step ? "bg-green-500" : i === state.step ? "bg-blue-600" : "bg-slate-200"}`}
          />
        ))}
      </div>

      <p className="text-sm leading-relaxed text-slate-700">{step.body}</p>

      {resolvedCase ? (
        <p className="mt-2 text-xs text-slate-500">
          Case: <span className="font-mono">{resolvedCase.case_id}</span> ({resolvedCase.mode})
        </p>
      ) : null}
      {unresolved && step.missingNote ? <p className="mt-2 text-xs text-amber-800">{step.missingNote}</p> : null}

      <button
        type="button"
        onClick={() => navigate(goTo)}
        className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
      >
        {step.goLabel}
      </button>

      <div className="mt-3 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => go(-1)}
          disabled={state.step === 0}
          className="inline-flex h-9 items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft size={16} aria-hidden="true" /> Back
        </button>
        {last ? (
          <button
            type="button"
            onClick={() => update({ open: false, step: 0 })}
            className="inline-flex h-9 items-center gap-1 rounded-lg border border-green-300 bg-green-50 px-3 text-sm font-semibold text-green-800 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            Finish
          </button>
        ) : (
          <button
            type="button"
            onClick={() => go(1)}
            className="inline-flex h-9 items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            Next <ChevronRight size={16} aria-hidden="true" />
          </button>
        )}
      </div>

      <div className="mt-3 text-right">
        <button
          type="button"
          onClick={() => update({ open: false, hidden: true })}
          className="text-xs text-slate-500 underline hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-300"
        >
          Dismiss tour
        </button>
      </div>
    </div>
  );
}
