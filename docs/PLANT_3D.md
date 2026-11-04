# 3D plant view: probe findings and integration

**What it is:** a 3D model of a *generic educational combined-cycle plant*. It comes from the
["Combined Cycle Power Plant"](https://www.educational-animation.org/en/combined-cycle-power-plant/) material on
educational-animation.org. The site states that the animation code is MIT and that text and graphics are CC BY 4.0.
The licence of the 3D viewer and scene itself has **not** been separately verified, so we only embed it through
its public URL and never copy assets. The UI includes the requested link credit. **It is not
the UCI facility.** The UCI dataset comes from an undisclosed plant with no published layout. The model only
helps orient the reader. It is not evidence.

- Viewer URL: `https://www.educational-animation.org/3d-scene-editor/index.html?scene=dd374706-ab57-47b8-929c-ae2c2b7da20a&mode=view`
  (the "SceneForge" 3D scene editor in view mode, three.js 0.164.1).
- Code: `apps/web/src/lib/plant3d.ts` (constants, mapping, postMessage helpers), `apps/web/src/components/Plant3D.tsx`
  (lazy iframe plus legend), and `apps/web/src/components/WhereToLook.tsx` (renders `<Plant3D>` for the rank-1 hypothesis).
- Probe: `scripts/probe_plant3d.py`. All numbers below come from the run on 2026-11-04 (`python scripts/probe_plant3d.py --json …`).

## Where it went wrong before

1. **The 3D viewer was never embedded.** `PlantAnimation.tsx` embeds the *2D* animation page
   (`web-animations/gas-fired-power-plant/…`), and that page has no message API. The earlier probe concluded
   "no API, the user must click". That is correct for the 2D page. The earlier probe also called the 3D scene's
   relation to the 2D animation "unconfirmed". It is now confirmed: the 3D scene contains exactly the 11 object
   names that the 2D animation's `Model3D.onObjectSelected` uses (see the table below).
2. **Object names must include `.obj`.** `selectObject` matches the raw scene name, and the raw names are
   `gas-turbine.obj` and so on. Sending `gas-turbine` selects nothing. The viewer still replies
   `{status: "ok"}` for an unknown name, so a caller that trusts the reply never notices the failure.
   `plant3d.ts` normalises names, and the UI only reports a highlight after the viewer's `objectSelected` event.
3. **Selection alone is hard to see.** A programmatic selection only recolours the object's edges blue. It does
   not zoom or dim other parts; that happens only when the user clicks a part. With the default camera, the
   intake (`air-and-gas-supply.obj`) sits at the right edge of the frame, and selecting it changed only
   **1.04 %** of the pixels (9,569 px, 2,400 of them to blue). `Plant3D` therefore also flies the camera to
   the object with `setCamera`, which changed 66.9 % of the frame and puts the filter house in the centre.
4. **Headless testing hides it.** Under headless Chromium the scene only renders with SwiftShader (CPU
   rendering). With plain `--use-gl=swiftshader` at 1280×720 the viewer never posted `ready`, even after 98 s.
   Once the WebGL page was busy, Playwright `page.evaluate`, `page.screenshot` and browser close stalled for
   minutes. Measured frame rate: **0.05–0.3 fps**. One canvas read-back took **157 s**. A naïve screenshot
   probe therefore times out and looks like "it doesn't work". A real browser with a GPU renders the scene
   normally; this is a test-harness limitation, not a product one.

## Verified facts (probe run 2026-11-04)

| Check | Result |
|---|---|
| `X-Frame-Options` / CSP `frame-ancestors` on the viewer page | **none**, so it can be iframed |
| `message` listener in `js/ExternalAPI.js` | yes, **no origin check** (it accepts commands from any embedding page) |
| Accepted actions | `selectObject`, `deselectAll`, `getSceneInfo`, `setCamera`, `setBackground`, `setMode`, `hideObject`, `showObject`, `setProperty`, `setPosition`/`setRotation`/`setScale`, `batch`, `addMesh`/`addPrimitive`/`removeObject`, `ping`, `requestScreenshot` |
| Message shape (parent → viewer) | `{ action: "selectObject", object: "air-and-gas-supply.obj" }` |
| Ready event (viewer → parent) | `{ type: "sceneEditor", action: "ready" }`, posted after the scene loads (15.4–28.4 s in headless runs) |
| Reply to each handled command | `{ type: "sceneEditor", action: <same>, data, status: "ok" }`, also when the name is not found |
| Selection event | `{ type: "sceneEditor", action: "objectSelected", data: { id, name: "air-and-gas-supply.obj", position, clickable, … } }` |
| Origin of all viewer messages | `https://www.educational-animation.org` (the UI filters on this) |
| Scene | name `Gaskraftwerk`, mode `view`, 11 objects, all visible and unlocked |
| `selectObject` via iframe postMessage | `gas-turbine.obj` → objectSelected ✔ · `air-and-gas-supply.obj` → ✔ · `gas-turbine` → ✘ (reply "ok") · `air-and-gas-supply` → ✘ (reply "ok") · `no-such-object.obj` → ✘ (reply "ok") |

All 11 names expected from the 2D animation are present, with no extras:
`general.obj`, `gas-turbine.obj`, `air-and-gas-supply.obj`, `exhaust-path-and-heat-transfer.obj`,
`steam-generation-and-steam-distribution.obj`, `steam-turbine.obj`, `condenser-and-cooling-circuit.obj`,
`generators-and-grid-connection.obj`, `exhaust-gas-treatment-and-chimney.obj`,
`water-treatment-and-auxiliary-services.obj`, `facility-infrastructure-and-operations.obj`.
`general.obj` and `steam-generation-and-steam-distribution.obj` are `clickable: false`: the user cannot
click-zoom them, but `selectObject` still selects them.

### Screenshots

These are the WebGL canvas, captured by the probe at 1280×720 with headless SwiftShader.

| | |
|---|---|
| Before (default camera) | `docs/screenshots/plant3d_probe_before.png` |
| `selectObject air-and-gas-supply.obj`: blue edges at the right edge of the frame, plus the editor's move arrows (not draggable in view mode) | `docs/screenshots/plant3d_probe_select_air_and_gas_supply_dotobj.png` |
| `selectObject gas-turbine` (no `.obj`): identical to before, 0 px changed | `docs/screenshots/plant3d_probe_select_gas_turbine.png` |
| `selectObject` + `setCamera` to the object pivot (offset × 0.45): the filter house fills the view, outlined in blue | `docs/screenshots/plant3d_probe_camera_air_and_gas_supply.png` |

## How the UI uses it

- `Plant3D` renders a 16:9 placeholder with a **Load 3D plant** button. Nothing is fetched from
  educational-animation.org until the user clicks, so the investigation page stays fast. The model is
  11 OBJ meshes, a few MB.
- After loading, it waits for `ready` (or 20 s if `ready` never arrives), then sends `selectObject` for
  the primary focus object at 0, 1.5 and 4 s. Each attempt also sends `getSceneInfo` until a camera move
  has happened. The first scene-info reply flies the camera to the object's pivot. The overview object
  `general.obj` keeps the default camera.
- The legend reads: "3D model: generic educational combined-cycle plant (educational-animation.org) — not the UCI
  facility". It also shows the focus labels, the credit link and the licence note above.
- The iframe is sandboxed (`allow-scripts allow-same-origin`) with `referrerPolicy="no-referrer"`. postMessage
  works under this sandbox, as the in-app check below shows.
- Once the viewer emits `objectSelected` for the focus object, the line reads "highlighted in the model (blue
  outline), confirmed by the viewer". If no confirmation arrives within 8 s of trying, the fallback line
  "If auto-highlight is unavailable, click <object> in the model" appears. That line is always shown
  if `PLANT3D_AUTO_SELECT_VERIFIED` in `plant3d.ts` is set to `false`. It is `true` because of the probe above.

### In-app check (dev server, case `case_76d34565b3dc`, rank-1 `intake_restriction`)

This run used a throwaway Playwright script against `vite` on port 5191, which proxies to the API on :8000. It
is not part of the repo.

- Before loading: `docs/screenshots/plant3d_app_before_load.png` shows the label "Suspected area: Air & fuel
  gas supply (intake filter house)", the Load button, the "not the UCI facility" badge and the credit line.
- After clicking **Load 3D plant**, the text "highlighted in the model (blue outline), confirmed by the viewer"
  appeared **14.6 s** later. That text only renders after the viewer's `objectSelected` event for
  `air-and-gas-supply.obj` arrives through the sandboxed iframe. No page errors were logged.

### Hypothesis → 3D object mapping (`PLANT3D_FOCUS`)

| Hypothesis key / area | 3D object(s), primary first |
|---|---|
| `intake_restriction` | `air-and-gas-supply.obj` (intake filter house, inlet duct, fuel gas) |
| `sensor_issue` | `gas-turbine.obj` (compressor instrumentation sits on the gas turbine) |
| `operating_condition` | `general.obj`, `air-and-gas-supply.obj` (ambient context) |
| `unknown` | `general.obj`, but WhereToLook renders no 3D view for "nothing to locate" |
| `electrical`, `thermal`, `grid` | `generators-and-grid-connection.obj` |
| `emissions` | `exhaust-gas-treatment-and-chimney.obj` |

Only the primary object is selected. The viewer supports one selection per message, and the others are listed
as text in the legend.

## Safety and limits

- View-only: the UI only sends `getSceneInfo`, `selectObject` and `setCamera`. The viewer also accepts
  mutating commands (`setProperty`, `removeObject`, …) from any origin. We never send them, and they would
  only change the public educational scene in the user's own browser tab. No plant system is reachable from
  here.
- The viewer is a third-party page. If its API or scene ID changes, the UI degrades to the click hint after
  8 s. Re-run `scripts/probe_plant3d.py` to re-verify (needs network; about 6–10 min in headless SwiftShader,
  mostly waiting on canvas read-backs).
- Highlight positions are approximate: the camera targets the object's pivot, not its bounding-box centre.
