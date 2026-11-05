#!/usr/bin/env python3
"""Build the motion-graphics explainer by DETERMINISTIC frame capture (no real-time screen recording).

    . .venv/bin/activate && python scripts/make_explainer_video.py [--jobs 4] [--scenes 1,2]

For each scene of submission/explainer/index.html?scene=N&capture=1&dur=S the page clock is frozen and
`window.__seek(ms)` sets every CSS/Web animation, SVG animation and canvas/counter ticker to an exact time.
Frame i is captured at i*1000/30 ms, so no frame can be dropped or duplicated by load. Narration: edge-tts
(en-US-GuyNeural, -5 %). Scene length = max(narration + 0.8 s, 14 s). Output: submission/video/thermomind_explainer.mp4
(h264 yuv420p 30 fps 1920x1080 + aac 48 kHz, <= 180 s). All numbers come from docs/EVALUATION.md and
docs/FINAL_VERIFICATION.md.
"""
from __future__ import annotations

import argparse, asyncio, hashlib, json, math, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_final_video import run, duration  # noqa: E402  (reuse ffmpeg helpers)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "submission/explainer/index.html"
OUT = ROOT / "submission/video/thermomind_explainer.mp4"
VOICE, RATE, FPS, AR, MIN_S, PAD_S, MAX_TOTAL = "en-US-GuyNeural", "-5%", 30, 48000, 14.0, 0.8, 180.0
CHROME_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--disable-gpu-compositing"]  # sw compositing: ~6x faster screenshots

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


def capture(task: tuple) -> dict:
    """Seek-and-screenshot frames [a, b) of scene n into fdir/f%05d.jpg (runs in its own process + browser)."""
    n, show, fdir, a, b_end = task
    from playwright.sync_api import sync_playwright
    fdir_p = Path(fdir); fdir_p.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=CHROME_ARGS)
        ctx = b.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto(f"file://{PAGE}?scene={n}&capture=1&dur={show:.3f}")
        pg.wait_for_function("window.sceneReady === true", timeout=60000)
        pg.evaluate("document.fonts.ready.then(() => document.fonts.size)")
        for i in range(a, b_end):
            pg.evaluate("window.__seek", i * 1000 / FPS)
            (fdir_p / f"f{i:05d}.jpg").write_bytes(pg.screenshot(type="jpeg", quality=92))
        ctx.close(); b.close()
    return {"scene": n, "a": a, "b": b_end, "secs": time.monotonic() - t0}


def frame_dupes(fdir: Path) -> tuple[int, int]:
    hs = [hashlib.md5(p.read_bytes()).digest() for p in sorted(fdir.glob("f*.jpg"))]
    return sum(a == b for a, b in zip(hs, hs[1:])), len(hs) - 1


def smoothness(video: Path, total: float, pairs: int = 20) -> list[tuple[float, float]]:
    """Decode the whole final video (640x360 gray, every frame, no input seeking - input seeking duplicates frames)
    and return (time, mean abs diff) for 20 evenly spaced consecutive-frame pairs, plus the whole-file count."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=640:360", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, 360, 640).astype(np.int16)
    d = np.abs(np.diff(a, axis=0)).reshape(len(a) - 1, -1)
    print(f"whole-file identical consecutive frames: {int((d.max(1) == 0).sum())}/{len(d)}")
    idx = [int((k + 0.5) * len(d) / pairs) for k in range(pairs)]
    return [(i / FPS, float(d[i].mean())) for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--chunk", type=int, default=100, help="frames per capture task")
    ap.add_argument("--scenes", default="")
    args = ap.parse_args()
    for i, t in enumerate(SCENES, 1):
        assert len(t.split()) <= 35, (i, len(t.split()))
    sel = [int(x) for x in args.scenes.split(",") if x] or list(range(1, len(SCENES) + 1))
    t_start = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="tm_explainer_"))
    shows, wavs = {}, {}
    for n in sel:
        wav = tmp / f"n{n}.wav"
        d = tts(SCENES[n - 1], wav)
        shows[n], wavs[n] = max(d + PAD_S, MIN_S), wav
        print(f"scene {n}: speech {d:.2f} s -> {shows[n]:.2f} s | {SCENES[n - 1]}", flush=True)
    t_cap = time.monotonic()
    # the clock is deterministic, so any frame range can be captured independently: split scenes into chunks
    tasks = [(n, shows[n], str(tmp / f"fr{n}"), a, min(a + args.chunk, math.ceil(shows[n] * FPS)))
             for n in sel for a in range(0, math.ceil(shows[n] * FPS), args.chunk)]
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for r in ex.map(capture, tasks):
            print(f"captured scene {r['scene']} frames {r['a']}-{r['b'] - 1} in {r['secs']:.1f} s", flush=True)
    print(f"capture wall time {time.monotonic() - t_cap:.1f} s", flush=True)
    segs, dup_total, pair_total = [], 0, 0
    for n in sel:
        fdir = tmp / f"fr{n}"
        dups, prs = frame_dupes(fdir); dup_total += dups; pair_total += prs
        seg = tmp / f"seg{n}.mp4"
        run("ffmpeg", "-y", "-framerate", FPS, "-i", fdir / "f%05d.jpg", "-i", wavs[n],
            "-filter_complex", "[1:a]adelay=300|300,apad[a];[0:v]format=yuv420p,setsar=1[v]",
            "-map", "[v]", "-map", "[a]", "-t", f"{shows[n]:.3f}", "-r", FPS, "-c:v", "libx264", "-preset", "slow",
            "-crf", 18, "-pix_fmt", "yuv420p", "-video_track_timescale", 15360,
            "-c:a", "aac", "-b:a", "192k", "-ar", AR, "-ac", 2, seg)
        segs.append(seg)
        print(f"scene {n}: identical consecutive captured frames {dups}/{prs}", flush=True)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    tmp_out = tmp / "final.mp4"
    run("ffmpeg", "-y", "-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", "-movflags", "+faststart", tmp_out)
    total = duration(tmp_out)
    print(f"total {total:.2f} s; identical consecutive captured frames overall {dup_total}/{pair_total}")
    if total > MAX_TOTAL:
        raise SystemExit(f"over {MAX_TOTAL} s")
    sm = smoothness(tmp_out, total)
    print("final-video consecutive-frame check (t, mean |diff| on 0-255):",
          json.dumps([(round(t, 1), round(d, 3)) for t, d in sm]))
    print(f"identical pairs in final video sample: {sum(d == 0 for _, d in sm)}/{len(sm)}")
    if len(sel) == len(SCENES):
        OUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(tmp_out, OUT)
        print(OUT)
    else:
        print(f"partial build left in {tmp_out}")
    print(f"render wall time {time.monotonic() - t_start:.1f} s")


if __name__ == "__main__":
    main()
