#!/usr/bin/env python
"""Probe the educational-animation.org SceneForge 3D viewer used by Plant3D.tsx.

Usage:
    . .venv/bin/activate
    python scripts/probe_plant3d.py [--json out.json]      # needs network; ~1-3 min

Phases (all against the live public site):
  0. Static: response headers of the viewer page (X-Frame-Options / CSP frame-ancestors) and the source of
     js/ExternalAPI.js + js/ObjectManager.js (message listener, origin check, accepted actions, events).
  1. Iframe protocol: a local test page (served via request interception on http://plant3d-probe.test/)
     iframes the viewer, waits for {type:'sceneEditor', action:'ready'}, then posts getSceneInfo and
     {action:'selectObject', object:<name>} for several spellings, delimited by ping messages, and reports
     every message the viewer sends back to the parent (via console.log -> Python).
  2. Visuals: loads the viewer top-level, feeds the same message objects to its own handler
     (sceneEditor.externalAPI.onMessage) and captures the WebGL canvas before/after selection and after a
     setCamera move -> docs/screenshots/plant3d_probe_*.png, plus a changed-pixel count.

Why two phases: in headless Chromium the viewer only renders with SwiftShader. Plain --use-gl=swiftshader at
1280x720 never reached 'ready' (98 s); ANGLE SwiftShader at 640x360 does (~11-25 s). With the WebGL iframe
busy, canvas read-backs (requestScreenshot) stalled the parent page for minutes and Playwright commands into
the page hung, so phase 1 does no read-backs and Python only listens to console events, and phase 2 captures
the canvas from the top-level page where page.evaluate stays responsive. Top-level, posting to window itself
would make the viewer answer its own replies (its handler treats every {action} object as a command), so phase 2
calls the handler directly with a source-less event instead -- same code path as postMessage.

Read-only: it only drives a public educational web page. It never touches any plant system.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOTS = REPO_ROOT / "docs" / "screenshots"
BASE = "https://www.educational-animation.org/3d-scene-editor/"
SCENE = "dd374706-ab57-47b8-929c-ae2c2b7da20a"
VIEWER_URL = f"{BASE}index.html?scene={SCENE}&mode=view"
EXPECTED = [
    "general.obj", "gas-turbine.obj", "air-and-gas-supply.obj", "exhaust-path-and-heat-transfer.obj",
    "steam-generation-and-steam-distribution.obj", "steam-turbine.obj", "condenser-and-cooling-circuit.obj",
    "generators-and-grid-connection.obj", "exhaust-gas-treatment-and-chimney.obj",
    "water-treatment-and-auxiliary-services.obj", "facility-infrastructure-and-operations.obj",
]
PROBE_ORIGIN = "http://plant3d-probe.test"
LAUNCH_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
VIEWPORT = {"width": 640, "height": 360}
SELECT_TARGETS = ["gas-turbine.obj", "air-and-gas-supply.obj", "gas-turbine", "air-and-gas-supply", "no-such-object.obj"]

IFRAME_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>plant3d probe</title>
<style>body{margin:0}iframe{width:640px;height:360px;border:0;display:block}</style></head>
<body><iframe id="v" src="__VIEWER_URL__"></iframe><script>
const TARGETS = __TARGETS__;
const t0 = performance.now();
const emit = (o) => console.log('PROBE_MSG ' + JSON.stringify(o));
window.addEventListener('message', (e) => {
  const d = e.data || {};
  const rec = {t: +((performance.now() - t0) / 1000).toFixed(2), origin: e.origin, type: d.type, action: d.action, status: d.status};
  if (d.action === 'objectSelected') rec.name = d.data && d.data.name;
  if (d.action === 'ping') rec.pingId = d.data && d.data.pingId;
  if (d.action === 'getSceneInfo' && d.data) rec.sceneInfo = {sceneName: d.data.sceneName, mode: d.data.mode, camera: d.data.camera,
     objects: d.data.objects.map((o) => ({name: o.name, visible: o.visible, locked: o.locked, clickable: o.clickable, dimOthers: o.dimOthers, position: o.position}))};
  emit(rec);
  if (d.type === 'sceneEditor' && d.action === 'ready') {
    const w = document.getElementById('v').contentWindow;
    w.postMessage({action: 'getSceneInfo'}, '*');
    TARGETS.forEach((name, i) => { w.postMessage({action: 'ping', pingId: i}, '*'); w.postMessage({action: 'selectObject', object: name}, '*'); });
    w.postMessage({action: 'deselectAll'}, '*');
    w.postMessage({action: 'ping', pingId: 'end'}, '*');
  }
});
</script></body></html>"""

PAUSE_RENDER_JS = """() => { const r = window.sceneEditor.sceneManager.renderer;
  if (!window.__origRender) { window.__origRender = r.render.bind(r); r.render = () => {}; } }"""
FPS_JS = """() => new Promise((res) => { let n = 0; const t = performance.now();
  const f = () => { n++; if (performance.now() - t < 8000) requestAnimationFrame(f); else res(n / ((performance.now() - t) / 1000)); };
  requestAnimationFrame(f); })"""
CAPTURE_JS = """(tag) => { const sm = window.sceneEditor.sceneManager; window.__origRender(sm.scene, sm.camera);
  (window.__shots = window.__shots || {})[tag] = sm.renderer.domElement.toDataURL('image/png'); return window.__shots[tag].length; }"""
DIFF_JS = """async ([a, b]) => {
  const load = (src) => new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.src = src; });
  const [ia, ib] = await Promise.all([load(window.__shots[a]), load(window.__shots[b])]);
  const w = Math.min(ia.width, ib.width), h = Math.min(ia.height, ib.height);
  const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d');
  x.drawImage(ia, 0, 0); const da = x.getImageData(0, 0, w, h).data;
  x.clearRect(0, 0, w, h); x.drawImage(ib, 0, 0); const db = x.getImageData(0, 0, w, h).data;
  let n = 0, blue = 0;
  for (let i = 0; i < da.length; i += 4) {
    const d = Math.abs(da[i] - db[i]) + Math.abs(da[i + 1] - db[i + 1]) + Math.abs(da[i + 2] - db[i + 2]);
    if (d > 30) { n++; if (db[i + 2] > 180 && db[i] < 120) blue++; }
  }
  return {width: w, height: h, changed: n, changedPct: +(100 * n / (w * h)).toFixed(3), changedToBlue: blue};
}"""
HANDLE_JS = """(msg) => { window.__sel = []; window.sceneEditor.externalAPI.onMessage({data: msg, source: null});
  const o = window.sceneEditor.objectManager.getSelectedObject(); return o ? o.displayName : null; }"""


def log(msg: str) -> None:
    print(f"[probe] {msg}", file=sys.stderr, flush=True)


def fetch(url: str) -> tuple[dict, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "thermomind-probe/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - public static page
        return {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")


def static_checks(out: dict) -> None:
    headers, html = fetch(VIEWER_URL)
    out["viewer_headers"] = {k: headers.get(k) for k in ("x-frame-options", "content-security-policy", "content-type")}
    out["iframe_blocked_by_headers"] = bool(headers.get("x-frame-options")) or "frame-ancestors" in (headers.get("content-security-policy") or "")
    out["uses_three_js"] = bool(re.search(r"three@[\d.]+", html))
    out["three_version"] = (re.search(r"three@([\d.]+)", html) or [None, None])[1]
    _, api = fetch(BASE + "js/ExternalAPI.js")
    out["external_api_js_bytes"] = len(api)
    out["has_message_listener"] = "addEventListener('message'" in api
    out["checks_event_origin"] = "event.origin" in api or ".origin" in api
    acts = re.findall(r"case '([A-Za-z]+)':", api[api.find("    onMessage(event) {"):api.find("    _setPositionDirect(obj, x, y, z) {")])
    out["accepted_actions"] = sorted(set(acts))
    code = api[api.find("export class ExternalAPI"):]
    out["emits"] = sorted(set(re.findall(r"action:\s*'([A-Za-z]+)'", code)) | ({"<echo of request action>"} if "action: msg.action" in code else set()))
    out["selectObject_handler"] = "selectByName(msg.object)" in api
    out["reply_ok_even_if_not_found"] = "status: 'ok'" in api and "this.selectByName(msg.object);\n                break;" in api
    _, om = fetch(BASE + "js/ObjectManager.js")
    out["getObjectByName_matches_raw_name"] = "if (obj.name === name) return obj;" in om
    out["getSceneInfo_returns_displayName_with_extension"] = "name:           this.displayName" in om and "return this.name + suffix;" in om


def phase_iframe(pw, out: dict) -> None:
    html = IFRAME_PAGE.replace("__VIEWER_URL__", VIEWER_URL).replace("__TARGETS__", json.dumps(SELECT_TARGETS))
    msgs: list[dict] = []

    def on_console(m) -> None:
        if m.text.startswith("PROBE_MSG "):
            msgs.append(json.loads(m.text[len("PROBE_MSG "):]))

    browser = pw.chromium.launch(args=LAUNCH_ARGS)
    page = browser.new_page(viewport=VIEWPORT)
    page.on("console", on_console)
    page.route(f"{PROBE_ORIGIN}/**", lambda route: route.fulfill(status=200, content_type="text/html", body=html))
    page.goto(f"{PROBE_ORIGIN}/test.html", wait_until="commit", timeout=90_000)
    log("phase 1: iframe test page requested; waiting for ping 'end' reply")
    try:
        page.wait_for_event("console", predicate=lambda m: '"pingId":"end"' in m.text, timeout=180_000)
    except Exception as exc:  # noqa: BLE001
        out["iframe_error"] = str(exc)[:300]
    ready = next((m for m in msgs if m.get("action") == "ready"), None)
    out["iframe_ready"] = ready
    info = next((m.get("sceneInfo") for m in msgs if m.get("action") == "getSceneInfo"), None) or {}
    objects = info.get("objects") or []
    out["scene_name"] = info.get("sceneName")
    out["scene_mode"] = info.get("mode")
    out["initial_camera"] = info.get("camera")
    out["scene_objects"] = objects
    names = [o.get("name") for o in objects]
    out["expected_names_present"] = {n: (n in names) for n in EXPECTED}
    out["extra_names"] = [n for n in names if n not in EXPECTED]
    # Split replies by the ping delimiters: ping(i) -> [objectSelected] -> selectObject reply.
    trials: dict[str, dict] = {}
    for i, name in enumerate(SELECT_TARGETS):
        try:
            a = next(k for k, m in enumerate(msgs) if m.get("action") == "ping" and m.get("pingId") == i)
        except StopIteration:
            continue
        nxt = next((k for k, m in enumerate(msgs) if k > a and m.get("action") == "ping"), len(msgs))
        chunk = msgs[a + 1:nxt]
        trials[name] = {
            "replies": [{k: m.get(k) for k in ("action", "status", "name", "origin")} for m in chunk],
            "objectSelected_emitted": any(m.get("action") == "objectSelected" for m in chunk),
        }
    out["iframe_select_trials"] = trials
    out["iframe_message_origins"] = sorted({m.get("origin") for m in msgs if m.get("origin")})
    log(f"phase 1 done: ready at {ready and ready.get('t')} s, {len(objects)} objects, "
        + ", ".join(f"{n}->{t['objectSelected_emitted']}" for n, t in trials.items()))
    # Closing a busy SwiftShader browser can hang; we leave it to process exit (os._exit in __main__).


def phase_visual(pw, out: dict) -> None:
    browser = pw.chromium.launch(args=LAUNCH_ARGS)
    page = browser.new_page(viewport=VIEWPORT)
    page.set_default_timeout(600_000)
    page.goto(VIEWER_URL, wait_until="commit", timeout=90_000)
    log("phase 2: viewer loading top-level")
    page.wait_for_event("console", predicate=lambda m: "[App] Bereit" in m.text, timeout=180_000)
    page.wait_for_timeout(2000)
    out["headless_swiftshader_fps"] = round(page.evaluate(FPS_JS), 2)
    log(f"phase 2: viewer ready; headless SwiftShader frame rate {out['headless_swiftshader_fps']} fps")
    # At ~0.3 fps queued GPU work makes every canvas read-back wait for the backlog. Stop the viewer's own
    # render loop (probe-only monkeypatch of renderer.render), let the queue drain, then render exactly once
    # per capture. Each read-back can still take minutes here.
    page.evaluate(PAUSE_RENDER_JS)
    page.wait_for_timeout(15000)
    shots: dict[str, str] = {}

    def capture(tag: str) -> None:
        t = time.time()
        page.evaluate(CAPTURE_JS, tag)
        log(f"phase 2: captured {tag} in {time.time() - t:.0f} s")
        url = page.evaluate("(t) => window.__shots[t]", tag)
        path = SHOTS / f"plant3d_probe_{tag}.png"
        path.write_bytes(base64.b64decode(url.split(",", 1)[1]))
        shots[tag] = str(path.relative_to(REPO_ROOT))

    capture("before")
    trials: dict[str, dict] = {}
    for name in ("air-and-gas-supply.obj", "gas-turbine"):
        page.evaluate("() => window.sceneEditor.objectManager.deselectAll()")
        selected = page.evaluate(HANDLE_JS, {"action": "selectObject", "object": name})
        page.wait_for_timeout(500)
        tag = "select_" + name.replace(".obj", "_dotobj").replace("-", "_")
        capture(tag)
        trials[name] = {"viewer_selected": selected, "screenshot": shots[tag],
                        "pixel_diff_vs_before": page.evaluate(DIFF_JS, ["before", tag])}
        log(f"phase 2: selectObject {name!r} -> selected={selected!r} diff={trials[name]['pixel_diff_vs_before']}")
    out["visual_select_trials"] = trials

    # setCamera towards the object's reported pivot (what Plant3D could do in addition to selectObject).
    info = page.evaluate("() => window.sceneEditor.externalAPI.getSceneInfo()")
    target = next((o for o in info["objects"] if o["name"] == "air-and-gas-supply.obj"), None)
    cam = info.get("camera") or {}
    if target and cam.get("position") and cam.get("target"):
        d = [cam["position"][i] - cam["target"][i] for i in range(3)]
        pos = [target["position"][i] + 0.45 * d[i] for i in range(3)]
        page.evaluate(HANDLE_JS, {"action": "selectObject", "object": "air-and-gas-supply.obj"})
        page.evaluate(HANDLE_JS, {"action": "setCamera", "position": pos, "target": target["position"]})
        page.wait_for_timeout(500)
        capture("camera_air_and_gas_supply")
        out["visual_camera_trial"] = {"target": target["position"], "position": pos, "camera_before": cam,
                                      "screenshot": shots["camera_air_and_gas_supply"],
                                      "pixel_diff_vs_before": page.evaluate(DIFF_JS, ["before", "camera_air_and_gas_supply"])}
    out["screenshots"] = shots


def run_phase_subprocess(phase: str, timeout_s: int) -> dict:
    """Run one browser phase in its own process (own Playwright driver + browser) and kill the whole
    process group afterwards. A busy SwiftShader browser congested a shared driver for minutes."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--phase", phase, "--json", tmp_path],
                            start_new_session=True)
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        log(f"phase {phase} timed out after {timeout_s} s")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # driver + chromium children
        except ProcessLookupError:
            pass
    try:
        return json.loads(Path(tmp_path).read_text() or "{}")
    except (OSError, ValueError):
        return {f"{phase}_error": "phase produced no JSON (timeout or crash)"}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write findings JSON here")
    ap.add_argument("--phase", choices=["all", "iframe", "visual"], default="all")
    args = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    out: dict = {"viewer_url": VIEWER_URL}
    if args.phase == "all":
        static_checks(out)
        log("static checks done: " + json.dumps({k: out[k] for k in ("iframe_blocked_by_headers", "checks_event_origin", "accepted_actions", "emits")}))
        out.update(run_phase_subprocess("iframe", 240))
        out.update(run_phase_subprocess("visual", 1500))
    else:
        pw = sync_playwright().start()  # never stopped: teardown of a busy SwiftShader browser can hang
        try:
            (phase_iframe if args.phase == "iframe" else phase_visual)(pw, out)
        except Exception as exc:  # noqa: BLE001 - report partial findings rather than nothing
            out[f"{args.phase}_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    text = json.dumps(out, indent=2, default=str)
    if args.json:
        Path(args.json).write_text(text)
    if args.phase == "all":
        print(text)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # skip Playwright teardown: closing a busy SwiftShader browser can block for minutes
