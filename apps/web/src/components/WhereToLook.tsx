import type React from "react";
import { AlertTriangle, Crosshair, Info, ListChecks, MapPin } from "lucide-react";
import type { DiagnosticReport } from "../api/types";
import { ANIMATION_OBJECTS, guideFor, type SchematicPart } from "../lib/subsystems";
import { PlantAnimation } from "./PlantAnimation";
import { HypothesisStatusPill } from "./StatusPill";

interface Props {
  report: DiagnosticReport | null;
  scenarioSynthetic: boolean;
  renderSchematic: (parts: SchematicPart[]) => React.ReactNode;
}

const GENERAL = ANIMATION_OBJECTS.filter((o) => o.id === "general");

function Header({ icon, children, synthetic }: { icon: React.ReactNode; children: React.ReactNode; synthetic: boolean }) {
  return (
    <div className="panel-header">
      <div className="panel-title flex items-center gap-2">
        {icon}
        {children}
      </div>
      {synthetic ? (
        <span className="rounded-md border border-yellow-400 bg-yellow-100 px-2 py-0.5 text-sm font-semibold text-yellow-900">
          Synthetic scenario
        </span>
      ) : null}
    </div>
  );
}

function NothingToLocate({ synthetic, message, detail, renderSchematic }: {
  synthetic: boolean;
  message: string;
  detail?: string;
  renderSchematic?: Props["renderSchematic"];
}) {
  return (
    <div className="panel">
      <Header icon={<MapPin size={18} />} synthetic={synthetic}>Where to look</Header>
      <div className="space-y-4 p-5">
        <div className="flex items-start gap-2 text-base text-ink-100">
          <Info size={18} className="mt-0.5 shrink-0 text-blue-700" />
          <div>
            <div className="font-semibold">{message}</div>
            {detail ? <p className="mt-1 text-ink-300">{detail}</p> : null}
          </div>
        </div>
        {renderSchematic ? (
          <div className="rounded-lg border border-ink-600 bg-white p-3">{renderSchematic([])}</div>
        ) : null}
        {renderSchematic ? <PlantAnimation clickHint={GENERAL} /> : null}
      </div>
    </div>
  );
}

export function WhereToLook({ report, scenarioSynthetic, renderSchematic }: Props) {
  if (report === null) {
    return <NothingToLocate synthetic={scenarioSynthetic} message="Nothing to locate — no report was produced for this case." />;
  }

  const sorted = [...report.hypotheses].sort((a, b) => a.rank - b.rank);
  const top = sorted[0];
  const noPossible = !sorted.some((h) => h.status === "possible");

  if (!top || top.key === "unknown" || (report.severity === "informational" && noPossible)) {
    return (
      <NothingToLocate
        synthetic={scenarioSynthetic}
        message="Nothing to locate — no notable deviation"
        detail="The analysis did not find a deviation that points to a specific plant area, so nothing is highlighted. The animation is shown for general orientation only."
        renderSchematic={renderSchematic}
      />
    );
  }

  const guide = guideFor(top.key);
  const unconfirmed = top.status === "inconclusive" || top.status === "not_supported";

  const seen = new Set<string>();
  const checks: { text: string; fromReport: boolean }[] = [];
  const reviewSentence = guide.engineer_checks[guide.engineer_checks.length - 1];
  const add = (text: string, fromReport: boolean) => {
    if (seen.has(text)) return;
    seen.add(text);
    checks.push({ text, fromReport });
  };
  guide.engineer_checks.slice(0, -1).forEach((t) => add(t, false));
  report.engineer_review_checks.forEach((t) => add(t, true));
  const rest = checks.filter((c) => c.text !== reviewSentence);
  checks.length = 0;
  checks.push(...rest, { text: reviewSentence, fromReport: false });

  return (
    <div className="panel">
      <Header icon={<Crosshair size={18} />} synthetic={scenarioSynthetic}>
        {unconfirmed ? "Candidate area (unconfirmed)" : `Where to look — ${guide.title}`}
      </Header>
      <div className="space-y-5 p-5">
        {unconfirmed ? (
          <div className="flex items-start gap-2 rounded-lg border border-yellow-400 bg-yellow-100 px-4 py-3 text-base font-semibold text-yellow-900">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            No confident location; verify data quality first
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {unconfirmed ? <span className="text-lg font-semibold text-ink-50">{guide.title}</span> : null}
          <div className="min-w-0 flex-1 text-lg font-semibold text-ink-50">
            {top.name}
          </div>
          <HypothesisStatusPill status={top.status} />
        </div>

        {guide.measurements.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Measurements</span>
            {guide.measurements.map((m) => (
              <span key={m} className="rounded-md border border-ink-600 bg-white px-2 py-0.5 font-mono text-sm text-ink-100">
                {m}
              </span>
            ))}
          </div>
        ) : null}

        <div>
          <div className="mb-2 flex items-center gap-1.5 text-base font-semibold text-ink-50">
            <MapPin size={16} /> Look here — highlighted on the generic schematic (not the UCI facility)
          </div>
          <div className="rounded-lg border border-ink-600 bg-white p-3">{renderSchematic(guide.schematic_parts)}</div>
        </div>

        <PlantAnimation clickHint={guide.animation_objects} />

        <ul className="list-disc space-y-1 pl-5 text-base text-ink-100">
          {guide.where_to_look.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>

        <div>
          <div className="label mb-2 flex items-center gap-1.5">
            <ListChecks size={14} /> Engineer checks
          </div>
          <ul className="columns-2 gap-6 text-base text-ink-100">
            {checks.map((c, i) => (
              <li key={i} className="mb-3 break-inside-avoid">
                <span
                  className={`mr-2 inline-block rounded-md border px-1.5 py-0.5 align-middle text-xs font-semibold ${
                    c.fromReport
                      ? "border-blue-300 bg-blue-50 text-blue-800"
                      : "border-ink-600 bg-ink-800 text-ink-300"
                  }`}
                >
                  {c.fromReport ? "from model report" : "bundled guide"}
                </span>
                {c.text}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-sm text-ink-300">
          What to look at, not how to operate. No plant control actions are possible from this software.
        </p>
      </div>
    </div>
  );
}
