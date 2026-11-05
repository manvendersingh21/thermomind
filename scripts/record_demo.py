#!/usr/bin/env python
"""Record the ThermoMind demo video (real product, real clicks, captions + voice-over).

Usage (backend already serving the built UI on :8000):
    . .venv/bin/activate
    pip install playwright==1.49.1 edge-tts && python -m playwright install chromium   # once
    python scripts/record_demo.py                  # -> submission/video/thermomind_demo.mp4 (narrated)
                                                   #    + thermomind_demo_silent.mp4, frames/, chapters.txt
    python scripts/record_demo.py --pace 0.9       # tighten every planned dwell by 10 %
    python scripts/record_demo.py --rate +15%      # speak faster (narration drives dwell times)
    python scripts/record_demo.py --no-narration   # captions only (no network needed for TTS)
    python scripts/record_demo.py --live           # ALSO record thermomind_live_investigation.mp4:
                                                   #   triggers a NEW live Muse Spark run on S02 (1-2 min)

The main video never triggers a new Meta investigation: it opens the stored meta_live
S02 case produced earlier by a real Muse Spark run. Nothing on the page is mocked; the
injected DOM is a caption bar and a cursor dot (headless Chromium draws no OS cursor),
and third-party educational-animation.org embeds are replaced by a labelled stub
(--with-animation loads them). Optional segments (/twin, /propose, /simulator,
/autonomy) are skipped when the route is not served. State changes during the main take:
none on the case; /propose records the human decision of a new proposal, and /simulator
may start an investigation from the simulated window (INVESTIGATE_FROM_SIM).

Timing: each storyboard segment starts with a caption (= the narration line) and
lasts max(planned dwell * pace, voice clip + 0.5 s). Voice clips are generated with
edge-tts (Microsoft neural voice, no key) and placed at the exact segment start
times measured during the recording, then muxed onto the video with ffmpeg.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "submission" / "video"
NARR_DIR = OUT_DIR / "narration"
W, H = 1920, 1080
MAX_SECONDS = 180.0

DEFAULT_S02_CASE = "case_76d34565b3dc"  # S02_INTAKE_RESTRICTION, meta_live, muse-spark-1.3
DEFAULT_VOICE = "en-US-GuyNeural"
INVESTIGATE_FROM_SIM = True  # click "Investigate last window" on /simulator (hover only when False)
DEFAULT_RATE = "+8%"
VOICE_LEAD_S = 0.15  # voice starts this long after the caption appears
VOICE_TAIL_S = 0.5  # minimum silence after a clip before the next segment

# Planned (minimum) dwell per segment in seconds, scaled by --pace. With narration the
# segment lasts at least clip + VOICE_TAIL_S. Tune here.
DWELL = {
    "overview": 6.0,
    "s02_case": 9.0,
    "s02_timeline": 6.0,
    "where": 8.0,
    "twin": 6.0,
    "inbox": 8.0,
    "propose_a": 8.0,
    "propose_b": 9.0,
    "sim_a": 7.0,
    "sim_b": 9.0,
    "ops": 8.0,
    "autonomy": 6.0,
    "eval": 12.0,
    "outro": 6.0,
    "live_setup": 5.0,
    "live_done": 5.0,
    "settle": 0.5,  # short pause after a click/navigation
}
# Scrolls and cursor glides are animated in-page (requestAnimationFrame): Playwright's
# stepped mouse.move / mouse.wheel cost 100-300 ms per CDP round-trip while recording.
SCROLL_PX_PER_S = 2400
SCROLL_MIN_S, SCROLL_MAX_S = 0.35, 1.3
GLIDE_MIN_S, GLIDE_MAX_S = 0.3, 0.7

REPO_URL = "github.com/manvendersingh21/thermomind"
PROPOSE_INTENT = "raise output by 5 MW"

# key -> (chapter, caption text). The caption is also the narration line unless SPOKEN overrides it.
# "{...}" fields are filled at run time from GET /api/models/evaluation (real numbers only).
CAPTIONS = {
    "overview": ("Overview", "ThermoMind reads a gas turbine's real public data (UCI, 2011–2015) and investigates deviations with evidence, never touching controls."),
    "s02_case": ("Live case S02", "A live case on Meta muse-spark-1.3: ranked hypotheses, and every evidence ID opens the deterministic computation behind it."),
    "s02_timeline": ("Live case S02", "Muse Spark calls the deterministic tools itself. Every call, result, latency and token count is stored, so every number is traceable."),
    "where": ("Where to look", "Where to look: the top hypothesis mapped onto a generic plant schematic. This scenario is a SYNTHETIC overlay on real rows, labelled at every layer."),
    "twin": ("Where to look", "The same spot on a 3D digital twin — a generic plant model, not the UCI facility."),
    "inbox": ("Inbox", "Findings route to the responsible engineer and their supervisor as work requests. Notifications are simulated; nothing is sent to a CMMS."),
    "propose_a": ("Propose an action", f"Proposal: '{PROPOSE_INTENT}'. Before anyone acts, the subsystem agents confer on what it would do elsewhere in the plant."),
    "propose_b": ("Propose an action", "Verdicts, consensus and dissent lead to a recommendation. The human decides — and nothing is executed."),
    "sim_a": ("Simulator", "A physics-based plant simulator lets teams rehearse: start it, then inject intake fouling."),
    "sim_b": ("Simulator", "Filter pressure (AFDP) rises and output falls; the last simulated window can be handed to an investigation."),
    "ops": ("Shift ops", "Routine triage and drafts run without a human — like this Muse Spark shift handover, marked DRAFT for supervisor sign-off. Anything that touches the plant always needs a human."),
    "autonomy": ("Autonomy policy", "The autonomy policy spells out who decides what."),
    "eval": ("Evaluation & Trust", "Untouched {holdout_year} holdout: baseline MAE {mae} MWh vs {naive_mae} MWh for a naive previous-value baseline. GPU challenger: benchmark only. Not a validated safety system."),
    "outro": ("ThermoMind", "Built today, from real public data, with humans in the loop.   " + REPO_URL),
    # --live recording (captions only)
    "live_setup": ("Live run", "Proof recording: starting a NEW investigation on S02 with Meta Muse Spark (muse-spark-1.3) live. Unedited wait."),
    "live_wait": ("Live run", "Waiting for the synchronous run: the model calls evidence tools, then the server validates its report."),
    "live_done": ("Live run", "The new case opens with the stored trace of what the model asked for and received."),
}
# Pronunciation-friendly overrides for the voice-over (same claims as the caption). None = silent.
SPOKEN: dict[str, str | None] = {
    "overview": "ThermoMind reads a gas turbine's real public data and investigates deviations with evidence, never touching controls.",
    "s02_case": "In this live case, Meta's Muse Spark 1.3 ranks hypotheses, and every evidence I D opens the deterministic computation behind it.",
    "where": "Where to look maps the top hypothesis onto a generic plant schematic. This scenario is a synthetic overlay on real rows, and it is labelled synthetic at every layer.",
    "twin": "A 3D twin marks the same spot, on a generic plant model.",
    "inbox": "Findings route to the responsible engineer and their supervisor. The notifications are simulated, and nothing is sent to a maintenance system.",
    "propose_a": "Before anyone acts on a proposal, like raising output by 5 megawatts, the subsystem agents confer on what it would do elsewhere in the plant.",
    "sim_a": "A physics-based plant simulator lets teams rehearse. We start it, and inject intake fouling.",
    "sim_b": "Filter pressure rises and output falls, and the last simulated window can be handed to an investigation.",
    "ops": "Routine triage and drafts run without a human, like this Muse Spark shift handover. Anything that touches the plant always needs one.",
    "eval": "On the untouched {holdout_year} holdout, the baseline's mean error is {mae_spoken} megawatt-hours, versus {naive_spoken} for a naive previous-value baseline. The GPU challenger is a benchmark only, and this is not a validated safety system.",
    "outro": "Built today, from real public data, with humans in the loop.",
    "live_setup": None, "live_wait": None, "live_done": None,
}
# Optional segments: skipped (with their narration) when the route is not served at record time.
OPTIONAL_ROUTES = {"twin": "/twin/{s02}", "propose_a": "/propose", "propose_b": "/propose",
                   "sim_a": "/simulator", "sim_b": "/simulator", "autonomy": "/autonomy"}


def fill_dynamic_text(base: str) -> None:
    """Put the real evaluation numbers (from the running API) into the eval caption / narration."""
    ev = api_get(base, "/api/models/evaluation")
    naive = ev["naive_baselines"].get("previous_observation") or min(ev["naive_baselines"].values(), key=lambda m: m["mae"])
    vals = {
        "holdout_year": "/".join(str(y) for y in ev["split"]["test_years"]),
        "mae": f"{ev['holdout']['mae']:.3f}", "naive_mae": f"{naive['mae']:.3f}",
        "mae_spoken": f"{ev['holdout']['mae']:.2f}", "naive_spoken": f"{naive['mae']:.2f}",
    }
    ch, txt = CAPTIONS["eval"]
    CAPTIONS["eval"] = (ch, txt.format(**vals))
    SPOKEN["eval"] = SPOKEN["eval"].format(**vals)
    print(f"eval numbers from API: {vals}")


INIT_SCRIPT = r"""
(() => {
  if (window.__tmOverlay) return; window.__tmOverlay = true;
  window.__tmPos = {x: 1150, y: 540};
  const ease = k => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
  const cursor = () => document.getElementById('tm-cursor');
  const place = (x, y) => { const c = cursor(); if (c) { c.style.left = x + 'px'; c.style.top = y + 'px'; } window.__tmPos = {x, y}; };
  const install = () => {
    const c = document.createElement('div');
    c.id = 'tm-cursor';
    Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', width:'24px', height:'24px',
      borderRadius:'50%', border:'3px solid rgba(15,23,42,0.9)', background:'rgba(250,204,21,0.55)',
      boxShadow:'0 0 0 3px rgba(255,255,255,0.9), 0 2px 8px rgba(0,0,0,0.35)', pointerEvents:'none',
      zIndex:'2147483647', transform:'translate(-50%,-50%)', transition:'transform 120ms ease'});
    document.documentElement.appendChild(c);
    place(window.__tmPos.x, window.__tmPos.y);
    document.addEventListener('mousemove', e => place(e.clientX, e.clientY), true);
    document.addEventListener('mousedown', () => { c.style.transform = 'translate(-50%,-50%) scale(0.6)'; }, true);
    document.addEventListener('mouseup', () => { c.style.transform = 'translate(-50%,-50%) scale(1)'; }, true);
  };
  window.__tmGlide = (x, y, ms) => new Promise(res => {
    const x0 = window.__tmPos.x, y0 = window.__tmPos.y, t0 = performance.now();
    const f = t => { const k = Math.min(1, (t - t0) / ms), e = ease(k);
      place(x0 + (x - x0) * e, y0 + (y - y0) * e); if (k < 1) requestAnimationFrame(f); else res(); };
    requestAnimationFrame(f);
  });
  window.__tmScroll = (dy, ms) => new Promise(res => {
    const y0 = window.scrollY, t0 = performance.now();
    const f = t => { const k = Math.min(1, (t - t0) / ms);
      window.scrollTo(0, y0 + dy * ease(k)); if (k < 1) requestAnimationFrame(f); else res(); };
    requestAnimationFrame(f);
  });
  if (document.documentElement) install(); else document.addEventListener('DOMContentLoaded', install);
})();
"""

# Third-party WebGL/SVG animations (educational-animation.org) embedded in the UI are heavy under
# software rendering: while they load, the recorded page drops to a few fps and the timeline drifts
# by tens of seconds. By default the recording serves this clearly-labelled stub in their place.
ANIMATION_HOST = "educational-animation.org"
ANIMATION_STUB = """<!doctype html><html><body style="margin:0;height:100vh;display:flex;align-items:center;
justify-content:center;background:#f1f5f9;font:500 22px/1.4 Inter,system-ui,sans-serif;color:#334155;text-align:center">
<div style="max-width:760px;padding:24px;border:2px dashed #94a3b8;border-radius:14px">
Interactive plant animation by educational-animation.org (MIT licence) loads here in the live app.<br>
<span style="font-size:17px;color:#64748b">Not rendered in this headless screen recording.</span></div></body></html>"""

CAPTION_JS = r"""
([chapter, text]) => {
  let bar = document.getElementById('tm-caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'tm-caption';
    Object.assign(bar.style, {position:'fixed', left:'50%', bottom:'28px', transform:'translateX(-50%)',
      maxWidth:'1500px', width:'calc(100% - 360px)', marginLeft:'128px', boxSizing:'border-box',
      padding:'14px 26px 16px', borderRadius:'14px', background:'rgba(8,12,18,0.84)',
      border:'1px solid rgba(255,255,255,0.12)', boxShadow:'0 8px 30px rgba(0,0,0,0.45)',
      color:'#f1f5f9', fontFamily:'Inter, ui-sans-serif, system-ui, sans-serif', zIndex:'2147483646',
      pointerEvents:'none', transition:'opacity 250ms ease', opacity:'0'});
    const ch = document.createElement('div'); ch.id = 'tm-caption-ch';
    Object.assign(ch.style, {fontSize:'16px', fontWeight:'700', letterSpacing:'0.08em', textTransform:'uppercase',
      color:'#facc15', marginBottom:'4px'});
    const tx = document.createElement('div'); tx.id = 'tm-caption-tx';
    Object.assign(tx.style, {fontSize:'28px', lineHeight:'1.3', fontWeight:'500'});
    bar.appendChild(ch); bar.appendChild(tx);
    document.documentElement.appendChild(bar);
  }
  const ch = document.getElementById('tm-caption-ch');
  const tx = document.getElementById('tm-caption-tx');
  if (tx.textContent === text && ch.textContent === chapter) { bar.style.opacity = '1'; return; }
  bar.style.opacity = '0';
  setTimeout(() => { ch.textContent = chapter; tx.textContent = text; bar.style.opacity = '1'; }, 200);
}
"""


# ====================================================================== narration (TTS)
def spoken_text(key: str) -> str | None:
    return SPOKEN[key] if key in SPOKEN else CAPTIONS[key][1]


def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def build_narration(keys: list[str], voice: str, rate: str) -> dict[str, tuple[Path, float]]:
    """Generate (or reuse cached) one mp3 per segment with edge-tts; return key -> (path, seconds)."""
    import edge_tts  # noqa: PLC0415 - optional dependency

    NARR_DIR.mkdir(parents=True, exist_ok=True)
    clips: dict[str, tuple[Path, float]] = {}
    for key in keys:
        text = spoken_text(key)
        if not text:
            continue
        h = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:10]
        path = NARR_DIR / f"{key}.{h}.mp3"
        if not path.exists():
            for old in NARR_DIR.glob(f"{key}.*.mp3"):
                old.unlink()
            for attempt in range(4):  # the edge-tts service occasionally returns no audio
                try:
                    tmp = path.with_suffix(".part")
                    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(tmp)))
                    tmp.rename(path)  # only complete clips land in the cache
                    break
                except Exception as exc:  # noqa: BLE001
                    path.with_suffix(".part").unlink(missing_ok=True)
                    if attempt == 3:
                        raise RuntimeError(f"edge-tts failed for segment {key!r}: {exc}") from exc
                    time.sleep(2 + 3 * attempt)
        trimmed = path.with_suffix(".wav")  # edge-tts pads ~0.5 s of silence at both ends: trim it
        if not trimmed.exists():
            for old in NARR_DIR.glob(f"{key}.*.wav"):
                old.unlink()
            sil = "silenceremove=start_periods=1:start_threshold=-50dB"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-af", f"{sil},areverse,{sil},areverse",
                            "-ar", "48000", "-ac", "1", str(trimmed)], check=True)
        clips[key] = (trimmed, media_duration(trimmed))
    total = sum(d for _, d in clips.values())
    print(f"narration: {len(clips)} clips, {total:.1f} s of speech (voice {voice}, rate {rate})")
    return clips


# ====================================================================== recorder
class Recorder:
    def __init__(self, page: Page, pace: float, base: str, clips: dict[str, tuple[Path, float]]):
        self.page = page
        self.pace = pace
        self.base = base
        self.clips = clips
        self.mouse = (W * 0.6, H * 0.5)
        self.t_origin = time.monotonic()  # ~ start of the page video
        self.t_start: float | None = None  # trim point (first real frame)
        self.markers: list[tuple[float, str]] = []
        self.seg_start: dict[str, float] = {}

    # ---------- timing ----------
    def now(self) -> float:
        return time.monotonic() - self.t_origin

    def mark_start(self) -> None:
        self.t_start = self.now()

    def marker(self, name: str) -> None:
        self.markers.append((self.now() - (self.t_start or 0.0), name))
        print(f"  [{self.markers[-1][0]:6.1f}s] {name}", flush=True)

    def segment_length(self, key: str) -> float:
        planned = DWELL.get(key, 3.0) * self.pace
        if key in self.clips:
            planned = max(planned, VOICE_LEAD_S + self.clips[key][1] + VOICE_TAIL_S)
        return planned

    def dwell(self, key: str) -> None:
        """Wait until the segment that started with caption(key) has lasted segment_length(key)."""
        start = self.seg_start.get(key, self.now())
        remaining = start + self.segment_length(key) - self.now()
        if remaining > 0:
            self.page.wait_for_timeout(int(remaining * 1000))

    def settle(self) -> None:
        self.page.wait_for_timeout(int(DWELL["settle"] * 1000))

    # ---------- overlay ----------
    def caption(self, key: str) -> None:
        chapter, text = CAPTIONS[key]
        self.page.evaluate(CAPTION_JS, [chapter, text])
        self.seg_start[key] = self.now()
        self.marker(key)

    def show(self, key: str) -> None:
        """Caption + dwell under the same key."""
        self.caption(key)
        self.dwell(key)

    # ---------- mouse ----------
    def glide(self, x: float, y: float, ms: int | None = None) -> None:
        if ms is None:
            dist = ((x - self.mouse[0]) ** 2 + (y - self.mouse[1]) ** 2) ** 0.5
            ms = int(1000 * min(GLIDE_MAX_S, max(GLIDE_MIN_S, dist / 1800)))
        self.page.evaluate("([x, y, ms]) => window.__tmGlide(x, y, ms)", [x, y, ms])
        self.page.mouse.move(x, y)  # one real event at the end -> real :hover state / tooltips
        self.mouse = (x, y)

    def _center(self, locator) -> tuple[float, float]:
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError(f"element has no box: {locator}")
        return box["x"] + min(box["width"] / 2, 260), box["y"] + box["height"] / 2

    def ensure_visible(self, locator, top: int = 160, bottom_margin: int = 220) -> None:
        box = locator.bounding_box()
        if box is None:
            locator.scroll_into_view_if_needed()
            return
        if box["y"] < 80 or box["y"] + box["height"] > H - bottom_margin:
            self.scroll_by(box["y"] - top)

    def hover(self, locator, pause_ms: int = 250) -> None:
        locator.wait_for(state="visible", timeout=8000)
        self.ensure_visible(locator)
        x, y = self._center(locator)
        self.glide(x, y)
        self.page.wait_for_timeout(pause_ms)

    def click(self, locator) -> None:
        self.hover(locator, pause_ms=150)
        x, y = self.mouse
        self.page.mouse.click(x, y)
        self.settle()

    # ---------- scrolling ----------
    def scroll_by(self, dy: float) -> None:
        max_dy = self.page.evaluate("document.documentElement.scrollHeight - window.innerHeight - window.scrollY")
        min_dy = -self.page.evaluate("window.scrollY")
        dy = max(min_dy, min(max_dy, dy))
        if abs(dy) < 4:
            return
        ms = int(1000 * min(SCROLL_MAX_S, max(SCROLL_MIN_S, abs(dy) / SCROLL_PX_PER_S)))
        self.page.evaluate("([dy, ms]) => window.__tmScroll(dy, ms)", [dy, ms])
        self.page.wait_for_timeout(150)

    def scroll_to(self, locator, top: int = 140) -> None:
        locator.wait_for(state="attached")
        box = locator.bounding_box()
        if box is None:
            locator.scroll_into_view_if_needed()
            return
        self.scroll_by(box["y"] - top)

    def scroll_top(self) -> None:
        self.scroll_by(-self.page.evaluate("window.scrollY"))

    # ---------- navigation ----------
    def nav(self, path: str) -> None:
        """Click the sidebar link for a route (by href, so nav label changes do not break the script)."""
        self.click(self.page.locator(f'aside a[href="{path}"]').first)
        self.idle()

    def idle(self, timeout_ms: int = 1500) -> None:
        try:  # pages may poll; do not block on network idle for long
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:  # noqa: BLE001
            pass


def api_get(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as r:  # noqa: S310 - local server
        return json.loads(r.read().decode())


def check_case(base: str, case_id: str, scenario: str) -> None:
    inv = api_get(base, f"/api/investigations/{case_id}")
    got = inv["scenario"]["scenario_id"]
    if inv.get("mode") != "meta_live" or got != scenario or not inv.get("report"):
        raise SystemExit(f"case {case_id}: expected meta_live {scenario} with report, got mode={inv.get('mode')} scenario={got}")
    print(f"  case {case_id}: {got} mode={inv['mode']} model={inv.get('meta_model')} review={inv.get('review')}")


MAIN_KEYS = [k for k in CAPTIONS if not k.startswith("live_")]


class SkipSegment(Exception):
    pass


def probe_routes(base: str, s02: str) -> set[str]:
    """Return the optional segment keys whose route is served (unknown routes redirect to '/')."""
    ok: set[str] = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        page.route(f"**/*{ANIMATION_HOST}/**", lambda route: route.abort())
        for path in sorted(set(OPTIONAL_ROUTES.values())):
            url_path = path.format(s02=s02)
            try:
                page.goto(f"{base}{url_path}", wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(1500)
                served = page.evaluate("location.pathname") == url_path
            except Exception:  # noqa: BLE001
                served = False
            print(f"  route {url_path}: {'served' if served else 'NOT served -> segment skipped'}")
            if served:
                ok.update(k for k, v in OPTIONAL_ROUTES.items() if v == path)
        browser.close()
    return ok


def soft(r: "Recorder", what: str, fn, *a, **kw):
    """Run an optional micro-action; log and continue if the element is missing."""
    try:
        return fn(*a, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"    (skipped: {what}: {str(exc).splitlines()[0][:120]})", flush=True)
        return None


def first_visible(page, candidates, timeout_ms: int = 2500):
    """Return the first locator among candidates that becomes visible, else None."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for loc in candidates:
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(200)
    return None


def go(r: "Recorder", path: str) -> None:
    """Navigate like a user: click the sidebar link if there is one, else client-side route change."""
    p = r.page
    link = p.locator(f'aside a[href="{path}"]')
    if link.count():
        r.click(link.first)
    else:
        p.evaluate("path => { history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate')); }", path)
    try:
        p.wait_for_function("path => location.pathname === path", arg=path, timeout=4000)
    except Exception as exc:  # noqa: BLE001
        raise SkipSegment(f"route {path} not served") from exc
    r.idle()
    p.wait_for_timeout(300)
    r.scroll_top()


# ====================================================================== storyboard
def storyboard_main(r: Recorder, s02: str, available: set[str]) -> None:
    p = r.page
    p.goto(f"{r.base}/", wait_until="domcontentloaded")
    r.idle(8000)
    p.get_by_text("Source rows").first.wait_for()
    p.wait_for_timeout(800)
    r.mark_start()

    def segment(key: str, body) -> None:
        if key in OPTIONAL_ROUTES and key not in available:
            return
        r.caption(key)
        try:
            body()
        except SkipSegment as exc:
            print(f"    segment {key} cut short: {exc}", flush=True)
        r.dwell(key)

    # 1 Overview: real-data badge + schematic
    def overview():
        r.hover(p.get_by_text("REAL UCI TURBINE DATA", exact=False).first)
        p.wait_for_timeout(1200)
        soft(r, "schematic", r.scroll_to, p.get_by_text("Monitored gas turbine train").first, top=90)
        r.glide(W * 0.55, H * 0.42)
    segment("overview", overview)

    # 2 Live S02 case: META LIVE badge, ranked hypotheses, ev_afdp_01 drawer, agent timeline
    def s02_case():
        go(r, f"/investigations/{s02}")
        p.get_by_text("Hypotheses (ranked)").first.wait_for()
        r.hover(p.get_by_text("META LIVE", exact=False).first)
        p.wait_for_timeout(800)
        hyp = p.get_by_text("Hypotheses (ranked)").first
        r.scroll_to(hyp, top=90)
        chip = p.locator("button.chip", has_text="ev_afdp_01").first  # layout-independent
        if not chip.count():
            chip = p.locator("button.chip").first
        soft(r, "evidence chip", lambda: r.click(chip))
        drawer = p.get_by_role("dialog").first  # evidence drawer (aria-labelledby = evidence id)
        soft(r, "drawer computation", lambda: r.hover(drawer.get_by_text("Computation", exact=True).first))
    segment("s02_case", s02_case)

    def s02_timeline():
        p.keyboard.press("Escape")  # close the evidence drawer
        p.wait_for_timeout(300)
        r.scroll_to(p.get_by_text("Agent timeline", exact=True).first, top=90)
        soft(r, "show args", r.click, p.get_by_role("button", name="show args").first)
        r.scroll_by(260)
    segment("s02_timeline", s02_timeline)

    # 3 Where to look (+ 3D twin when served)
    def where():
        r.scroll_to(p.locator(".panel-title", has_text=re.compile("Where to look|Candidate area")).first, top=90)
        soft(r, "look here", r.hover, p.get_by_text("Look here", exact=False).first)
        p.wait_for_timeout(1500)
        r.scroll_by(120)  # keep the highlighted schematic in view (the animation embed below is a stub)
    segment("where", where)

    def twin():
        go(r, f"/twin/{s02}")
        p.wait_for_timeout(2500)
        r.glide(W * 0.6, H * 0.45)
    segment("twin", twin)

    # 4 Inbox: routed work request (technician + supervisor, simulated notification)
    def inbox():
        go(r, "/inbox")
        soft(r, "notification badge", r.hover, p.locator("aside").get_by_text(re.compile(r"^\d+$")).first)
        wr = first_visible(p, [p.get_by_text("Work requests", exact=True)])
        if wr:
            r.scroll_to(wr, top=120)
        soft(r, "assignee", r.hover, p.get_by_text(re.compile("Assigned to")).first)
        soft(r, "simulated", r.hover, p.get_by_text(re.compile("SIMULATED WORKFLOW|simulated", re.I)).first)
    segment("inbox", inbox)

    # 5 Propose an action: agents confer, human decides, nothing executed
    def propose_a():
        go(r, "/propose")
        sel = first_visible(p, [p.locator("select")], 2000)
        if sel is not None:
            opts = sel.locator("option").all_inner_texts()
            pick = next((o for o in opts if s02 in o), None)
            if pick:
                r.hover(sel)
                sel.select_option(label=pick)
        box = first_visible(p, [p.get_by_placeholder(re.compile("intent|action|propos|what", re.I)),
                                p.locator("textarea"), p.locator("input[type=text]")], 2000)
        if box is not None:
            r.click(box)
            box.fill("")
            box.type(PROPOSE_INTENT, delay=45)
        btn = first_visible(p, [p.get_by_role("button", name=re.compile("deliberat|confer|propose|evaluate|ask the agents|run", re.I))], 2000)
        if btn is not None:
            r.click(btn)
        first_visible(p, [p.get_by_text(re.compile("consensus", re.I))], 60_000)
    segment("propose_a", propose_a)

    def propose_b():
        for pat in ("consensus", "dissent", "recommendation"):
            loc = first_visible(p, [p.get_by_text(re.compile(pat, re.I))], 1500)
            if loc is not None:
                soft(r, pat, r.hover, loc)
                p.wait_for_timeout(700)
        dec = first_visible(p, [p.get_by_role("button", name=re.compile(r"^\s*(approve|reject)", re.I))], 1500)
        if dec is not None:
            r.click(dec)
            p.wait_for_timeout(800)
            ne = first_visible(p, [p.get_by_text(re.compile("nothing (was )?executed|not executed", re.I))], 3000)
            if ne is not None:
                soft(r, "nothing executed", r.hover, ne)
    segment("propose_b", propose_b)

    # 6 Simulator: start, inject intake fouling, AFDP up / output down, investigate last window
    def sim_a():
        go(r, "/simulator")
        start = first_visible(p, [p.get_by_role("button", name=re.compile(r"start|run|play", re.I))], 3000)
        if start is not None:
            r.click(start)
        p.wait_for_timeout(2500)
        fault = first_visible(p, [p.get_by_role("button", name=re.compile("foul|intake|filter", re.I)),
                                  p.get_by_label(re.compile("foul|intake|filter", re.I))], 3000)
        if fault is not None:
            r.click(fault)
    segment("sim_a", sim_a)

    def sim_b():
        chart = first_visible(p, [p.locator(".recharts-wrapper"), p.locator("svg")], 2000)
        if chart is not None:
            soft(r, "sim chart", r.hover, chart)
        p.wait_for_timeout(4000)
        inv = first_visible(p, [p.get_by_role("button", name=re.compile("investigate last window", re.I))], 2000)
        if inv is not None:
            r.hover(inv)
            if INVESTIGATE_FROM_SIM:
                r.click(inv)
                p.wait_for_timeout(3000)
    segment("sim_b", sim_b)

    # 7 Ops handover draft + autonomy policy
    def ops():
        go(r, "/ops")
        soft(r, "draft badge", r.hover, p.get_by_text(re.compile("requires shift supervisor sign-off", re.I)).first)
        p.wait_for_timeout(800)
        soft(r, "model badge", r.hover, p.get_by_text(re.compile("MODEL-DRAFTED|META DRAFT", re.I)).first)
        r.scroll_by(350)
    segment("ops", ops)

    def autonomy():
        go(r, "/autonomy")
        p.wait_for_timeout(1200)
        r.scroll_by(400)
    segment("autonomy", autonomy)

    # 8 Evaluation: holdout vs naive, GPU challenger, disclaimer
    def evaluation():
        go(r, "/evaluation")
        p.get_by_text("Baseline model — expected TEY").first.wait_for()
        r.hover(p.locator("tr", has_text="Holdout").first)
        p.wait_for_timeout(1200)
        soft(r, "naive row", r.hover, p.locator("tr", has_text="previous observation").first)
        p.wait_for_timeout(1000)
        gpu = p.get_by_text("Production baseline vs GPU challenger").first
        if gpu.count():
            r.scroll_to(gpu, top=200)
            soft(r, "challenger row", r.hover, p.locator("tr", has_text="challenger").first)
            p.wait_for_timeout(1500)
        soft(r, "disclaimer", r.scroll_to, p.get_by_text("Safety disclaimer").first, top=160)
    segment("eval", evaluation)

    # 9 Close on Overview + repo URL
    def outro():
        go(r, "/")
        r.glide(W * 0.55, H * 0.35)
    segment("outro", outro)


def storyboard_live(r: Recorder, wait_s: int) -> str:
    p = r.page
    p.goto(f"{r.base}/", wait_until="domcontentloaded")
    r.idle(8000)
    p.get_by_text("Source rows").first.wait_for()
    p.wait_for_timeout(800)
    r.mark_start()
    scen = p.locator("label", has_text="Scenario").locator("select")
    r.scroll_to(p.get_by_text("Analysis window & scenario").first, top=110)
    scen.select_option("S02_INTAKE_RESTRICTION")
    r.idle()
    meta_box = p.locator("label", has_text="Use Meta Muse Spark (live)").locator("input[type=checkbox]")
    if not meta_box.is_checked():
        raise SystemExit("Meta checkbox is not checked/enabled: is MODEL_API_KEY configured on the server?")
    r.caption("live_setup")
    r.hover(meta_box)
    r.dwell("live_setup")
    r.click(p.get_by_role("button", name="Run diagnostic investigation"))
    r.caption("live_wait")
    t0 = time.monotonic()
    p.wait_for_url("**/investigations/case_*", timeout=wait_s * 1000)
    print(f"  live run returned after {time.monotonic() - t0:.1f} s")
    r.idle()
    case_id = p.url.rstrip("/").rsplit("/", 1)[-1]
    p.get_by_text("Agent timeline", exact=True).first.wait_for()
    r.caption("live_done")
    r.hover(p.get_by_text("META LIVE", exact=False).first)
    r.dwell("live_done")
    r.scroll_to(p.get_by_text("Hypotheses (ranked)").first, top=90)
    p.wait_for_timeout(int(5000 * r.pace))
    r.scroll_to(p.get_by_text("Agent timeline", exact=True).first, top=90)
    p.wait_for_timeout(int(6000 * r.pace))
    r.scroll_by(900)
    p.wait_for_timeout(int(4000 * r.pace))
    return case_id


# ====================================================================== recording + encoding
def stub_animation(route) -> None:
    if route.request.resource_type == "document":
        route.fulfill(status=200, content_type="text/html", body=ANIMATION_STUB)
    else:
        route.abort()


def record(base: str, pace: float, mode: str, s02: str, available: set[str], wait_s: int, headed: bool, clips,
           with_animation: bool = False, dry_run: bool = False):
    raw_dir = OUT_DIR / ("raw" if mode == "main" else "raw_live")
    if not dry_run:
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        raw_dir.mkdir(parents=True)
    with sync_playwright() as pw:
        # Default headless shell: it records the full 1920x1080 viewport (the new headless mode,
        # channel="chromium", loses the bottom ~88 px to window chrome). With the real cross-origin
        # animation iframe, the shell's screencast stalls unless the frame runs in-process.
        args = ["--disable-features=IsolateOrigins,site-per-process", "--disable-site-isolation-trials"] if with_animation else []
        browser = pw.chromium.launch(headless=not headed, args=args)
        video_opts = {} if dry_run else {"record_video_dir": str(raw_dir), "record_video_size": {"width": W, "height": H}}
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1, **video_opts)
        ctx.add_init_script(INIT_SCRIPT)
        if not with_animation:
            ctx.route(f"**/*{ANIMATION_HOST}/**", stub_animation)
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        r = Recorder(page, pace, base, clips)
        extra = None
        try:
            if mode == "main":
                storyboard_main(r, s02, available)
            else:
                extra = storyboard_live(r, wait_s)
            r.page.wait_for_timeout(400)
            t_end = r.now()
        except Exception:
            shot = OUT_DIR / "failure.png"
            try:
                page.screenshot(path=str(shot), timeout=10_000)
                print(f"  ! failed at {page.url}; screenshot -> {shot}", flush=True)
            except Exception:  # noqa: BLE001
                print(f"  ! failed at {page.url}; screenshot also failed", flush=True)
            raise
        finally:
            video = page.video
            ctx.close()
            browser.close()
        webm = Path(video.path()) if video else None
    return webm, r.t_start or 0.0, t_end, r.markers, extra


def encode(webm: Path, mp4: Path, trim_start: float, length: float) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{trim_start:.2f}", "-i", str(webm), "-t", f"{length:.2f}",
        "-vf", f"scale={W}:{H},fps=30", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-threads", "0",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4),
    ]
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def mux_narration(silent: Path, out: Path, markers: list[tuple[float, str]], clips) -> None:
    """Write each clip into a silent PCM track at its segment start time, then mux with the silent video.

    (Clips are 48 kHz mono s16 WAVs; building the track in Python is instant and exact, whereas an ffmpeg
    adelay/amix graph over ~25 inputs runs far slower than real time on a CPU-limited box.)
    """
    rate = 48000
    duration = media_duration(silent)
    pcm = bytearray(int(duration * rate) * 2)
    for t, key in markers:
        if key not in clips:
            continue
        with wave.open(str(clips[key][0]), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (rate, 1, 2):
                raise RuntimeError(f"{clips[key][0]}: expected 48 kHz mono s16")
            data = w.readframes(w.getnframes())
        off = int((t + VOICE_LEAD_S) * rate) * 2
        data = data[: max(0, len(pcm) - off)]
        pcm[off: off + len(data)] = data  # segments never overlap: each lasts >= clip + VOICE_TAIL_S
    track = OUT_DIR / "raw" / "narration_track.wav"
    track.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(track), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(track), "-map", "0:v", "-map", "1:a",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-shortest", "-movflags", "+faststart", str(out)]
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def ffprobe(mp4: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels",
         "-of", "json", str(mp4)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def export_frames(mp4: Path, markers: list[tuple[float, str]], wanted: dict[str, str]) -> list[Path]:
    frames_dir = OUT_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for key, fname in wanted.items():
        idx = next((i for i, (_, k) in enumerate(markers) if k == key), None)
        if idx is None or idx + 1 >= len(markers):
            continue
        t = markers[idx + 1][0] - 1.0  # end of the segment: scrolls and hovers have settled
        dst = frames_dir / fname
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1", str(dst)], check=True)
        out.append(dst)
    return out


def write_chapters(path: Path, markers: list[tuple[float, str]]) -> None:
    seen, lines = set(), []
    for t, key in markers:
        chapter = CAPTIONS[key][0]
        if chapter in seen:
            continue
        seen.add(chapter)
        t = 0.0 if not lines else max(0.0, t)  # YouTube chapters must start at 0:00
        lines.append(f"{int(t // 60)}:{int(t % 60):02d} {chapter}")
    path.write_text("\n".join(lines) + "\n")


def write_script(path: Path, markers: list[tuple[float, str]], clips) -> None:
    lines = ["# ThermoMind demo — narration / caption script (generated by scripts/record_demo.py)", ""]
    for t, key in markers:
        voice = spoken_text(key)
        dur = f"{clips[key][1]:.1f}s" if key in clips else "silent"
        lines.append(f"[{int(t // 60)}:{t % 60:04.1f}] ({CAPTIONS[key][0]}; voice {dur}) {CAPTIONS[key][1]}")
        if voice and voice != CAPTIONS[key][1]:
            lines.append(f"    spoken as: {voice}")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--pace", type=float, default=1.0, help="multiplier for every planned dwell (e.g. 0.9 to tighten)")
    ap.add_argument("--s02-case", default=DEFAULT_S02_CASE)
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="edge-tts voice (e.g. en-GB-RyanNeural)")
    ap.add_argument("--rate", default=DEFAULT_RATE, help="edge-tts speaking rate, e.g. +8%%")
    ap.add_argument("--no-narration", action="store_true", help="captions only; no TTS / audio track")
    ap.add_argument("--live", action="store_true", help="also record a NEW live Muse Spark run on S02 -> thermomind_live_investigation.mp4")
    ap.add_argument("--live-only", action="store_true", help="only the live recording (skip the main video)")
    ap.add_argument("--live-wait", type=int, default=300, help="max seconds to wait for the live run")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="drive the storyboard without recording (selector/timing check)")
    ap.add_argument("--reuse-raw", action="store_true",
                    help="skip recording; re-encode / re-mux from the last raw take (submission/video/raw/session.json)")
    ap.add_argument("--with-animation", action="store_true",
                    help=f"load the real {ANIMATION_HOST} embeds (heavy; the default serves a labelled stub)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"FAIL: {tool} not found (apt-get install -y ffmpeg)")
            return 2
    health = api_get(base, "/api/health")
    print(f"health: {json.dumps(health)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0

    if not args.live_only:
        check_case(base, args.s02_case, "S02_INTAKE_RESTRICTION")
        fill_dynamic_text(base)
        available = probe_routes(base, args.s02_case)
        clips = {} if args.no_narration else build_narration(MAIN_KEYS, args.voice, args.rate)
        session = OUT_DIR / "raw" / "session.json"
        if args.reuse_raw:
            sj = json.loads(session.read_text())
            webm, t0, t1 = Path(sj["webm"]), sj["t0"], sj["t1"]
            markers = [(m["t"], m["segment"]) for m in sj["markers"]]
            print(f"reusing raw take {webm.name} ({t1 - t0:.1f} s)")
        else:
            print(f"recording main demo (pace={args.pace}) ...")
            webm, t0, t1, markers, _ = record(base, args.pace, "main", args.s02_case, available, args.live_wait, args.headed,
                                              clips, args.with_animation, args.dry_run)
            if args.dry_run:
                print(f"dry run OK: storyboard took {t1 - t0:.1f} s (no video written)")
                return 0
            session.write_text(json.dumps({"webm": str(webm), "t0": t0, "t1": t1,
                                           "markers": [{"t": t, "segment": k} for t, k in markers]}, indent=1))
        silent = OUT_DIR / "thermomind_demo_silent.mp4"
        final = OUT_DIR / "thermomind_demo.mp4"
        if args.reuse_raw and silent.exists() and silent.stat().st_mtime > webm.stat().st_mtime:
            print(f"  reusing {silent.name}")
        else:
            encode(webm, silent, t0, t1 - t0)
        if clips:
            mux_narration(silent, final, markers, clips)
        else:
            shutil.copyfile(silent, final)
        info = ffprobe(final)
        dur = float(info["format"]["duration"])
        print(json.dumps(info, indent=2))
        frames = export_frames(silent, markers, {
            "overview": "01_overview.png",
            "s02_case": "02_live_case_evidence_drawer.png",
            "propose_b" if "propose_b" in available else "where": "03_propose_or_where_to_look.png",
        })
        write_chapters(OUT_DIR / "chapters.txt", markers)
        write_script(OUT_DIR / "narration_script.txt", markers, clips)
        (OUT_DIR / "markers.json").write_text(json.dumps([{"t": round(t, 2), "segment": k} for t, k in markers], indent=1) + "\n")
        print(f"wrote {final} ({dur:.1f} s, {final.stat().st_size / 1e6:.1f} MB) and {silent.name}; frames: {[f.name for f in frames]}")
        if dur > MAX_SECONDS:
            print(f"FAIL: {dur:.1f} s > {MAX_SECONDS} s — shorten DWELL / narration lines, lower --pace or raise --rate")
            rc = 1

    if args.live or args.live_only:
        print("recording LIVE investigation (creates a new stored case) ...")
        webm, t0, t1, markers, case_id = record(base, args.pace, "live", args.s02_case, set(), args.live_wait, args.headed, {}, args.with_animation)
        mp4 = OUT_DIR / "thermomind_live_investigation.mp4"
        encode(webm, mp4, t0, t1 - t0)
        info = ffprobe(mp4)
        print(json.dumps(info, indent=2))
        print(f"wrote {mp4} ({float(info['format']['duration']):.1f} s); new case: {case_id}")

    # raw/ (webm + session.json) is kept so --reuse-raw can re-encode without re-recording; it is git-ignored.
    failure = OUT_DIR / "failure.png"
    if rc == 0 and failure.exists():
        failure.unlink()
    return rc


if __name__ == "__main__":
    sys.exit(main())
