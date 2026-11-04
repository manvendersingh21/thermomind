/*
 * Probe conclusion (educational-animation.org, checked 2026-11-04):
 * - The embedded 2D animation page (web-animations/gas-fired-power-plant/en/...html) contains no
 *   postMessage listener, no URLSearchParams / location.search / hash handling, no object= or
 *   highlight parameter. It loads the OAL SVG board scripts only. No documented API: users must click.
 * - A different product, the "SceneForge" 3D scene editor (3d-scene-editor/index.html?scene=...&mode=view),
 *   does ship ExternalAPI.js with a postMessage API (action: selectObject / hideObject / setProperty,
 *   object: <name>) and URL params (mode, hide, color:Name, cam, ui). That 3D scene contains the same 11
 *   named objects as this 2D animation and IS embedded separately by Plant3D.tsx, which drives it with a
 *   verified selectObject / objectSelected protocol (see docs/PLANT_3D.md).
 * - Conclusion for THIS component: the 2D animation has no API; instruct the user to click the named objects.
 */
import { ExternalLink } from "lucide-react";
import type { AnimationObject } from "../lib/subsystems";

interface Props {
  clickHint?: AnimationObject[];
  compact?: boolean;
  className?: string;
}

export function PlantAnimation({ clickHint, compact = false, className = "" }: Props) {
  return (
    <div className={className}>
      {clickHint && clickHint.length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-base text-ink-100">
          <span>In the animation, click: </span>
          {clickHint.map((o) => (
            <span
              key={o.id}
              className="rounded-md border border-yellow-400 bg-yellow-100 px-2 py-0.5 text-sm font-semibold text-yellow-900"
            >
              {o.label}
            </span>
          ))}
        </div>
      ) : null}
      <div style={{ position: "relative", width: "100%", aspectRatio: "16/9" }}>
        <iframe
          src="https://www.educational-animation.org/web-animations/gas-fired-power-plant/en/gas-fired-power-plant.html"
          title="Interactive animation: Combined Cycle Power Plant"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: 0 }}
          sandbox="allow-scripts allow-same-origin"
          referrerPolicy="no-referrer"
          allowFullScreen
          loading="lazy"
        />
      </div>
      <div className={`mt-2 ${compact ? "text-sm" : "text-base"} text-ink-300`}>
        <a
          href="https://www.educational-animation.org/en/combined-cycle-power-plant/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-blue-700 underline hover:text-blue-800"
        >
          Combined Cycle Power Plant animation by educational-animation.org
          <ExternalLink size={14} />
        </a>
        <span> · educational-animation.org — animation code MIT; text and graphics CC BY 4.0</span>
        <div className="text-sm text-ink-400">Generic educational combined-cycle plant — not the UCI facility</div>
      </div>
    </div>
  );
}
