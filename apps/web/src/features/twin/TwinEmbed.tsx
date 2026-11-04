/**
 * Small embeddable 3D twin (e.g. on the Investigation page). Everything heavy — data hooks, the
 * three.js scene — is lazy-loaded, so importing this component adds ~1 kB to the importing chunk.
 *
 *   import { TwinEmbed } from "../features/twin/TwinEmbed";
 *   <TwinEmbed caseId={caseId} height={420} />
 */
import { Suspense, lazy } from "react";

const Inner = lazy(() => import("./TwinEmbedInner"));

export interface TwinEmbedProps {
  caseId?: string;
  /** Canvas height (px number or CSS length). Default 420. */
  height?: number | string;
}

export function TwinEmbed({ caseId, height = 420 }: TwinEmbedProps) {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center rounded-xl border border-ink-700 bg-[#f3f5f8] text-sm text-ink-400" style={{ height }}>
          Loading 3D plant…
        </div>
      }
    >
      <Inner caseId={caseId} height={height} />
    </Suspense>
  );
}

export default TwinEmbed;
