/*
 * 3D plant view — educational-animation.org "SceneForge" 3D viewer, embedded via its public URL only.
 * (Site: animation code MIT; text and graphics CC BY 4.0; the 3D viewer's own licence is not separately verified.)
 *
 * Verified by scripts/probe_plant3d.py on 2026-11-04 (details + screenshots in docs/PLANT_3D.md):
 * - The viewer page sends no X-Frame-Options / CSP frame-ancestors header, so it can be iframed.
 * - js/ExternalAPI.js registers a window "message" listener with NO origin check. Messages are plain
 *   objects keyed by `action`: { action: "selectObject", object: "gas-turbine.obj" }.
 * - Once the scene has loaded it posts { type: "sceneEditor", action: "ready" } to window.parent
 *   (observed ~15 s after iframe creation in headless Chromium), replies
 *   { type: "sceneEditor", action, data, status: "ok" } to every handled message — status is "ok" even
 *   when the object name is NOT found — and emits
 *   { type: "sceneEditor", action: "objectSelected", data: { id, name: "gas-turbine.obj", ... } } on selection.
 * - The 11 scene object names match the 2D animation's Model3D names exactly, including ".obj".
 *   Names WITHOUT ".obj" (e.g. "gas-turbine") silently select nothing, so selectObject() normalises.
 * - Programmatic selection draws the selected object's edges in blue (plus the editor's move-arrows at the
 *   object's pivot; they are not draggable in view mode). It does NOT zoom the camera or dim other parts —
 *   that only happens when the user clicks a part. With the default camera, air-and-gas-supply.obj sits at
 *   the right edge of the frame, so selection alone changed only ~1% of pixels. We therefore also move the
 *   camera with { action: "setCamera", position, target } towards the object's pivot from getSceneInfo
 *   (verified: frames the intake filter house).
 * We only send view-only messages (getSceneInfo / selectObject / setCamera / deselectAll). Nothing here can reach any plant
 * system; it drives a public educational web page.
 */

export const PLANT3D_SCENE_ID = "dd374706-ab57-47b8-929c-ae2c2b7da20a";
export const PLANT3D_URL = `https://www.educational-animation.org/3d-scene-editor/index.html?scene=${PLANT3D_SCENE_ID}&mode=view`;
export const PLANT3D_ORIGIN = "https://www.educational-animation.org";
export const PLANT3D_CREDIT_URL = "https://www.educational-animation.org/en/combined-cycle-power-plant/";

/** Object names in the 3D scene (as used by the 2D animation's Model3D.onObjectSelected). */
export const PLANT3D_OBJECTS = {
  general: "general.obj",
  gasTurbine: "gas-turbine.obj",
  airAndGasSupply: "air-and-gas-supply.obj",
  exhaustPath: "exhaust-path-and-heat-transfer.obj",
  steamGeneration: "steam-generation-and-steam-distribution.obj",
  steamTurbine: "steam-turbine.obj",
  condenser: "condenser-and-cooling-circuit.obj",
  generators: "generators-and-grid-connection.obj",
  exhaustTreatment: "exhaust-gas-treatment-and-chimney.obj",
  waterTreatment: "water-treatment-and-auxiliary-services.obj",
  facility: "facility-infrastructure-and-operations.obj",
} as const;

export type Plant3DObjectName = (typeof PLANT3D_OBJECTS)[keyof typeof PLANT3D_OBJECTS];

export const PLANT3D_LABELS: Record<Plant3DObjectName, string> = {
  "general.obj": "Overview",
  "gas-turbine.obj": "Gas turbine",
  "air-and-gas-supply.obj": "Air & fuel gas supply (intake filter house)",
  "exhaust-path-and-heat-transfer.obj": "Exhaust path & heat transfer",
  "steam-generation-and-steam-distribution.obj": "Steam generation & distribution",
  "steam-turbine.obj": "Steam turbine",
  "condenser-and-cooling-circuit.obj": "Condenser & cooling circuit",
  "generators-and-grid-connection.obj": "Generators & grid connection",
  "exhaust-gas-treatment-and-chimney.obj": "Exhaust gas treatment & chimney",
  "water-treatment-and-auxiliary-services.obj": "Water treatment & auxiliary services",
  "facility-infrastructure-and-operations.obj": "Facility infrastructure & operations",
};

export function plant3dLabel(name: string): string {
  return (PLANT3D_LABELS as Record<string, string>)[name] ?? name;
}

/** Hypothesis key / feature area -> 3D object(s) to focus, most specific first. */
export const PLANT3D_FOCUS: Record<string, Plant3DObjectName[]> = {
  intake_restriction: [PLANT3D_OBJECTS.airAndGasSupply],
  sensor_issue: [PLANT3D_OBJECTS.gasTurbine], // compressor instrumentation sits on the gas turbine
  operating_condition: [PLANT3D_OBJECTS.general, PLANT3D_OBJECTS.airAndGasSupply], // ambient context
  unknown: [PLANT3D_OBJECTS.general],
  electrical: [PLANT3D_OBJECTS.generators],
  thermal: [PLANT3D_OBJECTS.generators],
  emissions: [PLANT3D_OBJECTS.exhaustTreatment],
  grid: [PLANT3D_OBJECTS.generators],
};

export function plant3dFocusFor(key: string | null | undefined): Plant3DObjectName[] {
  if (key && Object.prototype.hasOwnProperty.call(PLANT3D_FOCUS, key)) return PLANT3D_FOCUS[key];
  return PLANT3D_FOCUS.unknown;
}

/**
 * Set from the probe findings (scripts/probe_plant3d.py, docs/PLANT_3D.md).
 * true  -> postMessage selectObject was observed to select the object (objectSelected event + outline).
 * false -> show the "click <object> in the model" fallback instruction.
 */
export const PLANT3D_AUTO_SELECT_VERIFIED = true;

export interface SceneEditorMessage {
  type: "sceneEditor";
  action: string;
  data?: unknown;
  status?: string;
}

function post(iframe: HTMLIFrameElement | null, msg: Record<string, unknown>): boolean {
  const win = iframe?.contentWindow;
  if (!win) return false;
  win.postMessage(msg, PLANT3D_ORIGIN);
  return true;
}

/** Scene object names carry the ".obj" extension; the viewer matches them exactly. */
export function normaliseObjectName(name: string): string {
  return name.toLowerCase().endsWith(".obj") ? name : `${name}.obj`;
}

/**
 * Ask the viewer to select (blue edge outline) an object by name. Returns false if the iframe is not
 * available. Success is only known from the viewer's objectSelected event (its reply says "ok" regardless).
 */
export function selectObject(iframe: HTMLIFrameElement | null, name: string): boolean {
  return post(iframe, { action: "selectObject", object: normaliseObjectName(name) });
}

export function deselectAll(iframe: HTMLIFrameElement | null): boolean {
  return post(iframe, { action: "deselectAll" });
}

/** Ask the viewer for its scene info; the reply arrives as { action: "getSceneInfo", data: SceneInfo }. */
export function requestSceneInfo(iframe: HTMLIFrameElement | null): boolean {
  return post(iframe, { action: "getSceneInfo" });
}

type Vec3 = [number, number, number];

export interface SceneInfo {
  camera?: { position?: Vec3; target?: Vec3 };
  objects?: { name?: string; position?: Vec3; clickable?: boolean }[];
}

/** Fraction of the current camera-to-target offset kept when flying to an object (probe-tested: 0.45). */
export const PLANT3D_ZOOM_FRACTION = 0.45;

/**
 * Compute a camera that looks at the object's pivot from the current viewing direction, closer in.
 * Returns null for the overview object or when the scene info lacks the data.
 */
export function cameraFocusFor(info: SceneInfo, name: string): { position: Vec3; target: Vec3 } | null {
  const wanted = normaliseObjectName(name);
  if (wanted === PLANT3D_OBJECTS.general) return null;
  const obj = info.objects?.find((o) => o.name === wanted);
  const cam = info.camera;
  const isVec = (v: unknown): v is Vec3 => Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === "number" && Number.isFinite(x));
  if (!obj || !isVec(obj.position) || !cam || !isVec(cam.position) || !isVec(cam.target)) return null;
  const target = obj.position;
  const position = [0, 1, 2].map((i) => target[i] + PLANT3D_ZOOM_FRACTION * (cam.position![i] - cam.target![i])) as Vec3;
  return { position, target };
}

export function setCamera(iframe: HTMLIFrameElement | null, focus: { position: Vec3; target: Vec3 }): boolean {
  return post(iframe, { action: "setCamera", position: focus.position, target: focus.target });
}

function isSceneEditorMessage(e: MessageEvent): e is MessageEvent<SceneEditorMessage> {
  const d = e.data as Partial<SceneEditorMessage> | null;
  return e.origin === PLANT3D_ORIGIN && !!d && typeof d === "object" && d.type === "sceneEditor" && typeof d.action === "string";
}

/** Listen for any viewer message (ready, objectSelected, replies). Returns an unsubscribe function. */
export function onViewerMessage(
  iframe: HTMLIFrameElement | null,
  cb: (msg: SceneEditorMessage) => void,
): () => void {
  const handler = (e: MessageEvent) => {
    if (!isSceneEditorMessage(e)) return;
    if (iframe && e.source !== iframe.contentWindow) return;
    cb(e.data);
  };
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}

/** Listen for objectSelected events (user click in the model, or our selectObject). */
export function onObjectSelected(
  iframe: HTMLIFrameElement | null,
  cb: (name: string, data: Record<string, unknown>) => void,
): () => void {
  return onViewerMessage(iframe, (msg) => {
    if (msg.action !== "objectSelected" || !msg.data || typeof msg.data !== "object") return;
    const data = msg.data as Record<string, unknown>;
    cb(typeof data.name === "string" ? data.name : String(data.id ?? ""), data);
  });
}
