/** Side panel: what is going off, where to look, who owns it, and equipment involved (information only). */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Crosshair, Info, ListChecks, MapPin, UserRound, Wrench, Zap } from "lucide-react";
import { EvidenceDrawer } from "../../components/EvidenceDrawer";
import { HypothesisStatusPill } from "../../components/StatusPill";
import { SourceBadge } from "../../components/SourceBadge";
import type { TwinController } from "./controller";
import { NO_COMMANDS } from "./locate";
import { ProvChip } from "./provenance";

const ROUTE_FALLBACK: Record<string, string> = { electrical: "electrical_engineer", emissions: "environmental_engineer" };

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-ink-700 px-4 py-3">
      <div className="label mb-2 flex items-center gap-1.5">
        {icon}
        {title}
      </div>
      {children}
    </section>
  );
}

export function LookHerePanel({ ctl }: { ctl: TwinController }) {
  const { inv, location: loc, data } = ctl;
  const [openEv, setOpenEv] = useState<string | null>(null);
  const evidenceById = useMemo(() => new Map((inv?.evidence ?? []).map((e) => [e.evidence_id, e])), [inv]);
  const primary = loc.hotspots.find((h) => h.kind === "primary") ?? null;
  const secondary = loc.hotspots.filter((h) => h !== primary);

  const routingKey = loc.routingKey ?? (loc.hotspots.some((h) => h.id === "emissions-stack") ? "emissions" : null);
  const routing = routingKey ? data.personas?.routing_table[routingKey] : undefined;
  const assigneeId = routing?.assignee ?? (routingKey ? ROUTE_FALLBACK[routingKey] : undefined);
  const persona = data.personas?.personas.find((p) => p.persona_id === assigneeId);
  const supervisor = data.personas?.personas.find((p) => p.persona_id === (routing?.supervisor ?? persona?.supervisor));

  return (
    <div className="panel overflow-hidden" data-testid="twin-panel">
      <div className="panel-header flex-wrap gap-2">
        <div className="panel-title flex items-center gap-2">
          <MapPin size={18} /> Where to look
        </div>
        <div className="flex flex-wrap gap-1.5">
          {inv ? (
            loc.synthetic ? (
              <SourceBadge variant="synthetic" label="SYNTHETIC SCENARIO" size="sm" />
            ) : (
              <SourceBadge variant="real" label="REAL DATA ONLY" size="sm" />
            )
          ) : null}
          <SourceBadge variant="review" label="HUMAN REVIEW REQUIRED" size="sm" />
        </div>
      </div>

      <div className="px-4 pb-3">
        {ctl.invLoading ? <div className="text-sm text-ink-400">Loading case…</div> : null}
        {ctl.invError ? <div className="text-sm text-red-700">Case: {ctl.invError}</div> : null}
        {inv?.report ? (
          <div className="mb-2 text-sm text-ink-300">
            <Link to={`/investigations/${inv.case_id}`} className="font-mono text-blue-700 underline">
              {inv.case_id}
            </Link>{" "}
            · {inv.scenario.title}
            <div className="mt-0.5 font-medium text-ink-100">{inv.report.title}</div>
          </div>
        ) : null}

        {loc.located && loc.top ? (
          <div className="space-y-2">
            {loc.unconfirmed ? (
              <div className="flex items-start gap-2 rounded-md border border-yellow-400 bg-yellow-100 px-3 py-2 text-sm font-semibold text-yellow-900">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" /> Candidate area (unconfirmed) — verify data quality first
              </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-semibold text-ink-50">{loc.top.name}</span>
              <HypothesisStatusPill status={loc.top.status} />
              <span className="text-xs text-ink-400">rank {loc.top.rank}</span>
            </div>
            {primary ? (
              <button
                className="flex w-full items-center gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-left text-sm font-semibold text-red-800 hover:bg-red-100"
                onClick={() => ctl.flyTo(primary.equipment)}
                data-testid="twin-primary-hotspot"
              >
                <Crosshair size={16} className="shrink-0" />
                <span className="flex-1">{primary.label}</span>
                {primary.synthetic ? <ProvChip p="synthetic" /> : null}
              </button>
            ) : null}
          </div>
        ) : (
          <div className="flex items-start gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900" data-testid="twin-nothing">
            <Info size={16} className="mt-0.5 shrink-0" />
            <span className="font-semibold">{loc.nothingMessage ?? "No notable deviation — nothing to locate"}</span>
          </div>
        )}

        {secondary.length > 0 ? (
          <div className="mt-3 space-y-1.5">
            <div className="label">{loc.located ? "Other screening flags in this window" : "Screening flags in this window"}</div>
            {secondary.map((h) => (
              <button
                key={h.id}
                className="flex w-full items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-left text-xs text-amber-900 hover:bg-amber-100"
                onClick={() => ctl.flyTo(h.equipment)}
              >
                <Crosshair size={13} className="mt-0.5 shrink-0" />
                <span className="flex-1">
                  <b>{h.label}</b>
                  <span className="block text-amber-800/80">{h.reason}</span>
                </span>
                <ProvChip p={h.source} />
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {loc.top && inv ? (
        <Section icon={<ArrowRight size={14} />} title="Cited evidence">
          <div className="flex flex-wrap gap-1.5">
            {loc.top.supporting_evidence_ids.map((id) => (
              <button
                key={id}
                className="rounded-md border border-green-300 bg-green-50 px-1.5 py-0.5 font-mono text-xs text-green-800 hover:bg-green-100"
                onClick={() => setOpenEv(id)}
                title="Supporting evidence — click to open"
              >
                + {id}
              </button>
            ))}
            {loc.top.contradicting_evidence_ids.map((id) => (
              <button
                key={id}
                className="rounded-md border border-red-300 bg-red-50 px-1.5 py-0.5 font-mono text-xs text-red-800 hover:bg-red-100"
                onClick={() => setOpenEv(id)}
                title="Contradicting evidence — click to open"
              >
                − {id}
              </button>
            ))}
          </div>
          <Link to={`/investigations/${inv.case_id}`} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 underline">
            Open case page <ArrowRight size={12} />
          </Link>
        </Section>
      ) : null}

      {loc.checks.length > 0 ? (
        <Section icon={<ListChecks size={14} />} title="Engineer checks (bundled guide)">
          <ul className="list-disc space-y-1 pl-4 text-sm text-ink-100">
            {loc.checks.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      {persona || data.workRequests.length > 0 ? (
        <Section icon={<UserRound size={14} />} title="Responsible (routing)">
          {persona ? (
            <div className="text-sm text-ink-100">
              <b>{persona.role}</b> <span className="text-ink-400">({persona.name})</span>
              {supervisor ? <div className="text-xs text-ink-400">Supervisor: {supervisor.role}</div> : null}
              {routing?.field_inspection ? <div className="text-xs text-ink-400">Field inspection expected (per permit-to-work).</div> : null}
            </div>
          ) : null}
          {data.workRequests.map((w) => (
            <div key={w.id} className="mt-2 rounded-md border border-ink-600 bg-white px-2.5 py-1.5 text-xs">
              <div className="font-semibold text-ink-50">{w.title}</div>
              <div className="text-ink-400">
                {w.id} · {w.status} · {w.assignment_label}
              </div>
            </div>
          ))}
          {inv && data.workRequests.length === 0 ? <div className="mt-1 text-xs text-ink-400">No work request raised for this case yet (see Inbox).</div> : null}
        </Section>
      ) : null}

      {loc.involved.length > 0 ? (
        <Section icon={<Wrench size={14} />} title="Equipment involved (information only)">
          <ul className="space-y-1.5">
            {loc.involved.map((it, i) => (
              <li key={`${it.name}-${i}`} className="text-sm">
                <div className="flex items-center gap-1.5">
                  {it.equipment ? (
                    <button className="text-left font-semibold text-blue-700 hover:underline" onClick={() => ctl.flyTo(it.equipment)}>
                      {it.name}
                    </button>
                  ) : (
                    <span className="font-semibold text-ink-100">{it.name}</span>
                  )}
                  <ProvChip p={it.provenance} />
                </div>
                <div className="text-xs text-ink-300">{it.note}</div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-400">
            Information only — this software issues no commands.
            {loc.involved.some((i) => i.equipment === "breaker_52g" || i.equipment === "hv_switchgear") ? ` ${NO_COMMANDS}` : ""}
          </p>
        </Section>
      ) : null}

      <Section icon={<Zap size={14} />} title="Electrical screening">
        <label className="flex items-start gap-2 text-xs text-ink-200">
          <input type="checkbox" className="mt-0.5" checked={ctl.thermalDemo} onChange={(e) => ctl.setThermalDemo(e.target.checked)} />
          <span>
            Add the <b>SYNTHETIC</b> hot-connection demo (thermal scenario T01) to see how an electrical finding is located. Temperatures are SIMULATED from real load.
          </span>
        </label>
        {data.thermal ? <p className="mt-1 text-[11px] text-ink-400">{data.thermal.banner}</p> : null}
      </Section>

      {data.errors.length > 0 ? (
        <Section icon={<AlertTriangle size={14} />} title="Partial data">
          <ul className="space-y-0.5 text-xs text-red-700">
            {data.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      <EvidenceDrawer
        evidence={openEv ? (evidenceById.get(openEv) ?? null) : null}
        missingId={openEv && !evidenceById.has(openEv) ? openEv : null}
        onClose={() => setOpenEv(null)}
      />
    </div>
  );
}
