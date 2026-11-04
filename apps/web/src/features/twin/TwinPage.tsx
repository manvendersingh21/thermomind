/**
 * /twin and /twin/:caseId — native 3D digital twin of a GENERIC combined-cycle plant driven by the
 * UCI data. Read-only decision support: shows what is going off and where to look; no control actions.
 * Default export so App can lazy-load it: `const TwinPage = lazy(() => import("./features/twin/TwinPage"))`.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Box, ShieldAlert } from "lucide-react";
import { errorMessage, listInvestigations } from "../../api/client";
import type { Investigation } from "../../api/types";
import { SourceBadge } from "../../components/SourceBadge";
import { useTwinController } from "./controller";
import { LookHerePanel } from "./LookHerePanel";
import { LiveReadout, Scrubber } from "./Scrubber";
import { TWIN_BANNER, TwinView } from "./TwinView";

function caseOption(c: Investigation) {
  const top = [...(c.report?.hypotheses ?? [])].sort((a, b) => a.rank - b.rank)[0];
  return `${c.case_id} · ${c.scenario.scenario_id}${c.scenario_label === "synthetic_overlay" ? " (synthetic)" : ""} · ${top ? `${top.key ?? top.name} (${top.status})` : c.status}`;
}

function CasePicker({ caseId }: { caseId?: string }) {
  const nav = useNavigate();
  const [cases, setCases] = useState<Investigation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    listInvestigations(ac.signal)
      .then(setCases)
      .catch((e) => {
        if (!ac.signal.aborted) setError(errorMessage(e));
      });
    return () => ac.abort();
  }, []);
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-0.5 sm:max-w-xl">
      <span className="label">Case</span>
      <select
        className="w-full truncate rounded-md border border-ink-600 bg-white px-2 py-1.5 text-sm"
        value={caseId ?? ""}
        onChange={(e) => nav(e.target.value ? `/twin/${e.target.value}` : "/twin")}
        aria-label="Select investigation case"
      >
        <option value="">No case — live data only (2014 #1200–#1319)</option>
        {caseId && cases && !cases.some((c) => c.case_id === caseId) ? <option value={caseId}>{caseId}</option> : null}
        {(cases ?? []).map((c) => (
          <option key={c.case_id} value={c.case_id}>
            {caseOption(c)}
          </option>
        ))}
      </select>
      {error ? <span className="text-xs text-red-700">{error}</span> : null}
    </label>
  );
}

export default function TwinPage() {
  const { caseId } = useParams<{ caseId?: string }>();
  const ctl = useTwinController(caseId);

  return (
    <div className="space-y-4" data-testid="twin-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-ink-50">
            <Box size={24} className="text-blue-700" /> 3D plant twin
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-300">
            See what is going off and where to look: live flows of air, fuel, gas, steam, water and electricity, scaled by the hourly UCI
            measurements, with the case finding pinned to the equipment.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <SourceBadge variant="real" size="sm" />
          {ctl.location.synthetic ? <SourceBadge variant="synthetic" size="sm" /> : null}
          <SourceBadge variant="model" size="sm" />
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-900" role="note">
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
        <span>
          {TWIN_BANNER}. Read-only decision support — every finding requires human review.
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <CasePicker caseId={caseId} />
        {caseId ? (
          <Link to={`/investigations/${caseId}`} className="btn btn-secondary px-3 py-1.5 text-sm">
            Open case
          </Link>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-3 lg:col-span-8">
          <TwinView ctl={ctl} height="var(--twin-h)" className="[--twin-h:60vh] lg:[--twin-h:min(72vh,760px)]" />
          <div className="panel space-y-3 p-3">
            <Scrubber ctl={ctl} />
            <LiveReadout ctl={ctl} />
            {ctl.data.loading ? <div className="text-xs text-ink-400">Loading series…</div> : null}
          </div>
        </div>
        <div className="lg:col-span-4">
          <LookHerePanel ctl={ctl} />
        </div>
      </div>
    </div>
  );
}
