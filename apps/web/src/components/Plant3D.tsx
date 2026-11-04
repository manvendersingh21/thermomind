import { useEffect, useRef, useState } from "react";
import { Box, ExternalLink } from "lucide-react";
import {
  PLANT3D_AUTO_SELECT_VERIFIED,
  PLANT3D_CREDIT_URL,
  PLANT3D_URL,
  cameraFocusFor,
  normaliseObjectName,
  onViewerMessage,
  plant3dLabel,
  requestSceneInfo,
  selectObject,
  setCamera,
  type SceneInfo,
} from "../lib/plant3d";

interface Props {
  /** 3D object names to select once the viewer is ready (first one is the primary focus). */
  focus?: string[];
  /** e.g. "Suspected area: Air & fuel gas supply (intake filter house)". */
  label?: string;
  className?: string;
}

const RETRY_DELAYS_MS = [0, 1500, 4000];
/** If the viewer never posts "ready" (slow network / old viewer build), try selecting anyway after this. */
const NO_READY_FALLBACK_MS = 20000;
/** After trying to select, how long to wait for the viewer's objectSelected confirmation before showing the click hint. */
const CONFIRM_TIMEOUT_MS = 8000;

/**
 * Lazy 3D view of a generic educational combined-cycle plant (educational-animation.org — animation code MIT; text and graphics CC BY 4.0;
 * licence of the 3D viewer not separately verified; used via its public embed URL).
 * Nothing loads until the user presses "Load 3D plant". Focus objects are selected over postMessage
 * once the viewer reports ready (or after a fallback delay), retried a few times. View-only.
 */
export function Plant3D({ focus = [], label, className = "" }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [ready, setReady] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmTimedOut, setConfirmTimedOut] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const cameraMovedRef = useRef(false);
  const focusKey = focus.join("|");
  const primary = focus[0];

  // Listen for viewer messages (ready / objectSelected) while the iframe exists.
  useEffect(() => {
    if (!loaded) return;
    cameraMovedRef.current = false;
    const off = onViewerMessage(iframeRef.current, (msg) => {
      if (msg.action === "ready") setReady(true);
      // Fly the camera to the primary focus once (view-only; the user can orbit away freely afterwards).
      if (msg.action === "getSceneInfo" && msg.data && primary && !cameraMovedRef.current) {
        const cam = cameraFocusFor(msg.data as SceneInfo, primary);
        if (cam) {
          cameraMovedRef.current = true;
          setCamera(iframeRef.current, cam);
        }
      }
      if (msg.action === "objectSelected" && msg.data && typeof msg.data === "object") {
        const name = (msg.data as { name?: unknown }).name;
        if (typeof name === "string") setSelected(name);
      }
    });
    const fallback = window.setTimeout(() => setReady(true), NO_READY_FALLBACK_MS);
    return () => {
      off();
      window.clearTimeout(fallback);
    };
  }, [loaded, primary]);

  // Once ready, select the primary focus object (retried: meshes may still be streaming in).
  useEffect(() => {
    if (!loaded || !ready || !primary) return;
    setConfirmTimedOut(false);
    const timers = RETRY_DELAYS_MS.map((d) =>
      window.setTimeout(() => {
        selectObject(iframeRef.current, primary);
        if (!cameraMovedRef.current) requestSceneInfo(iframeRef.current);
      }, d),
    );
    timers.push(window.setTimeout(() => setConfirmTimedOut(true), CONFIRM_TIMEOUT_MS));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [loaded, ready, primary, focusKey]);

  const focusLabels = focus.map(plant3dLabel);
  const confirmed = !!primary && selected === normaliseObjectName(primary);
  // Click hint: always when the probe could not verify auto-select; otherwise only if this viewer instance
  // did not confirm the selection in time.
  const showClickHint = focusLabels.length > 0 && (!PLANT3D_AUTO_SELECT_VERIFIED || (loaded && !confirmed && confirmTimedOut));

  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-base text-ink-100">
        <Box size={16} className="text-blue-700" />
        <span className="font-semibold">3D plant view</span>
        {label ? (
          <span className="rounded-md border border-yellow-400 bg-yellow-100 px-2 py-0.5 text-sm font-semibold text-yellow-900">
            {label}
          </span>
        ) : null}
      </div>

      <div style={{ position: "relative", width: "100%", aspectRatio: "16/9" }} className="overflow-hidden rounded-lg border border-ink-600 bg-ink-800">
        {loaded ? (
          <iframe
            ref={iframeRef}
            src={PLANT3D_URL}
            title="3D model: generic educational combined-cycle power plant"
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: 0 }}
            sandbox="allow-scripts allow-same-origin"
            referrerPolicy="no-referrer"
            allowFullScreen
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4 text-center">
            <button
              type="button"
              onClick={() => setLoaded(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-base font-semibold text-blue-800 hover:bg-blue-100"
            >
              <Box size={18} /> Load 3D plant
            </button>
            <span className="text-sm text-ink-300">Loads a WebGL model from educational-animation.org (a few MB).</span>
          </div>
        )}
      </div>

      <div className="mt-2 space-y-1 text-sm text-ink-300">
        <div>
          <span className="rounded-md border border-ink-600 bg-white px-2 py-0.5 text-xs font-semibold text-ink-100">
            3D model: generic educational combined-cycle plant (educational-animation.org) — not the UCI facility
          </span>
        </div>
        {focusLabels.length > 0 ? (
          <div>
            Focus: {focusLabels.join(", ")}
            {loaded && confirmed ? (
              <span className="text-ink-100"> · highlighted in the model (blue outline), confirmed by the viewer — drag to orbit, scroll to zoom</span>
            ) : loaded && selected ? (
              <span> · viewer reports selected: <span className="font-mono">{selected}</span></span>
            ) : loaded && !confirmTimedOut ? (
              <span> · loading model…</span>
            ) : null}
          </div>
        ) : null}
        {showClickHint ? (
          <div className="text-ink-100">
            If auto-highlight is unavailable, click <strong>{focusLabels[0]}</strong> in the model.
          </div>
        ) : null}
        <a
          href={PLANT3D_CREDIT_URL}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-blue-700 underline hover:text-blue-800"
        >
          Combined Cycle Power Plant 3D model by educational-animation.org
          <ExternalLink size={14} />
        </a>
        <span> · educational-animation.org — animation code MIT; text and graphics CC BY 4.0 (licence of the 3D viewer not separately verified; used via its public embed URL)</span>
      </div>
    </div>
  );
}
