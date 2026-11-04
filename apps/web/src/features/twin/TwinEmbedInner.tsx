/** Lazy-loaded body of TwinEmbed (keeps the core bundle small). */
import { Link } from "react-router-dom";
import { Maximize2 } from "lucide-react";
import { useTwinController } from "./controller";
import { Scrubber } from "./Scrubber";
import { TwinView } from "./TwinView";

export default function TwinEmbedInner({ caseId, height }: { caseId?: string; height: number | string }) {
  const ctl = useTwinController(caseId);
  const primary = ctl.location.hotspots.find((h) => h.kind === "primary");
  return (
    <div className="space-y-2" data-testid="twin-embed">
      <TwinView ctl={ctl} height={height} compact />
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <Scrubber ctl={ctl} compact />
        </div>
        <Link to={caseId ? `/twin/${caseId}` : "/twin"} className="btn btn-secondary px-2.5 py-1 text-xs">
          <Maximize2 size={13} /> Open full 3D twin
        </Link>
      </div>
      <div className="text-xs text-ink-300">
        {primary ? <b className="text-red-700">{primary.label}</b> : ctl.location.nothingMessage}
      </div>
    </div>
  );
}
