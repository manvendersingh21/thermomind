#!/usr/bin/env python3
"""Build the motion-graphics explainer: submission/explainer/index.html?scene=N recorded with Playwright
(1920x1080 video), narrated with edge-tts (en-US-GuyNeural, -5%), muxed and concatenated with ffmpeg.

    . .venv/bin/activate && python scripts/make_explainer_video.py

Scene length = max(narration + 0.8 s, 14 s). Output: submission/video/thermomind_explainer.mp4 (<= 180 s).
All numbers come from docs/EVALUATION.md and docs/FINAL_VERIFICATION.md.
"""
from __future__ import annotations

import asyncio, shutil, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_final_video import run, duration  # noqa: E402  (reuse ffmpeg helpers)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "submission/explainer/index.html"
OUT = ROOT / "submission/video/thermomind_explainer.mp4"
VOICE, RATE, FPS, AR, MIN_S, PAD_S, MAX_TOTAL = "en-US-GuyNeural", "-5%", 30, 48000, 14.0, 0.8, 180.0

SCENES = [
    "ThermoMind. Agents meet a real power plant: Meta Muse Spark investigates gas turbine data through tools, and a human reviews every finding.",
    "The problem: deviations flood in, one engineer must decide which deserve an investigation, and the reasoning lives in a spreadsheet. The data has no fault labels.",
    "The loop: thirty six thousand real hourly rows, a baseline with 1.293 megawatt-hours holdout error versus 12.957 naive, Muse Spark with tools, a validator, then a human. Four live cases, zero validation errors.",
    "Where to look: every claim links to computed evidence, and the 3D twin pins the finding to equipment. Here, a synthetic intake restriction at the filter house.",
    "Eleven plant roles. A proposed action is routed to subsystem agents, which confer, support or oppose. A human decides. ThermoMind executes nothing.",
    "A physics simulator lets teams rehearse faults. Inject intake fouling, and the filter pressure drop climbs. Everything here is simulated and labelled.",
    "An explicit autonomy policy: agents alone may compute, draft and route. Humans review decisions. Anything touching the plant stays human only, with no software path.",
    "For generation companies and O and M contractors: a pilot on one turbine, in shadow mode, measuring engineer time. A prototype on public data. ThermoMind.",
]


def tts(text: str, out: Path) -> float:
    import edge_tts
    mp3 = out.with_suffix(".mp3")
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(str(mp3)))
            if mp3.stat().st_size > 1000:
                break
        except Exception:
            if attempt == 3:
                raise
    run("ffmpeg", "-y", "-i", mp3, "-af",
        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB,areverse", "-ar", AR, "-ac", 2, out)
    return duration(out)


def record(n: int, dur: float, tmp: Path) -> tuple[Path, float]:
    """Record scene n; return (webm, seconds of pre-roll to trim before the animation clock starts)."""
    from playwright.sync_api import sync_playwright
    vdir = tmp / f"v{n}"
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader"])
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(vdir),
                            record_video_size={"width": 1920, "height": 1080})
        t0 = time.monotonic()
        pg = ctx.new_page()
        pg.goto(f"file://{PAGE}?scene={n}&dur={dur:.2f}")
        pg.wait_for_function("window.sceneReady === true", timeout=30000)
        pre = time.monotonic() - t0
        try:
            pg.wait_for_function("window.sceneDone === true", timeout=int((dur + 10) * 1000), polling=200)
        except Exception:
            pass
        pg.wait_for_timeout(300)
        ctx.close(); b.close()
    return next(vdir.glob("*.webm")), pre


def main():
    for i, t in enumerate(SCENES, 1):
        assert len(t.split()) <= 35, (i, len(t.split()))
    tmp = Path(tempfile.mkdtemp(prefix="tm_explainer_"))
    segs = []
    for n, text in enumerate(SCENES, 1):
        wav = tmp / f"n{n}.wav"
        d = tts(text, wav)
        show = max(d + PAD_S, MIN_S)
        webm, pre = record(n, show, tmp)
        seg = tmp / f"seg{n}.mp4"
        run("ffmpeg", "-y", "-ss", f"{pre:.3f}", "-i", webm, "-i", wav,
            "-filter_complex", "[1:a]adelay=300|300,apad[a];[0:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1,tpad=stop_mode=clone:stop_duration=2[v]",
            "-map", "[v]", "-map", "[a]", "-t", f"{show:.3f}", "-r", FPS, "-c:v", "libx264", "-preset", "medium",
            "-crf", 20, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", AR, "-ac", 2, seg)
        segs.append(seg)
        print(f"scene {n}: speech {d:.1f} s -> {show:.1f} s (pre-roll trimmed {pre:.2f} s) | {text}", flush=True)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    tmp_out = tmp / "final.mp4"
    run("ffmpeg", "-y", "-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", "-movflags", "+faststart", tmp_out)
    total = duration(tmp_out)
    print(f"total {total:.2f} s")
    if total > MAX_TOTAL:
        raise SystemExit(f"over {MAX_TOTAL} s")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmp_out, OUT)
    print(OUT)


if __name__ == "__main__":
    main()
