#!/usr/bin/env python3
"""Build the final submission video: PART A (narrated product walkthrough, unchanged)
+ PART B (narrated pitch-deck slides captured with Playwright at 1920x1080).

    . .venv/bin/activate && python scripts/make_final_video.py \
        --part-a submission/video/thermomind_demo_product_only.mp4

Narration: edge-tts en-US-GuyNeural (same voice as scripts/record_demo.py). Each slide is shown for
max(clip + 0.6 s, 8 s). Output: submission/video/thermomind_demo.mp4 (h264 yuv420p 30 fps, aac 48 kHz).
All numbers spoken come from docs/EVALUATION.md.
"""
from __future__ import annotations

import argparse, asyncio, json, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "submission/deck/index.html"
VOICE = "en-US-GuyNeural"

# (deck position used in the URL hash, narration)  -- each <= 30 words
SLIDES = [
    (2, "The problem: every week an engineer must decide which turbine deviations deserve an investigation. "
        "Alarms are noisy, sensors drift, and the reasoning lives in one spreadsheet."),
    (3, "Real use cases: alarm triage, instrument drift versus false trips, wash and filter timing, "
        "emissions excursions, cross-team what-ifs, shift handover, and grid-event readiness. All read-only."),
    (5, "What is real and what is simulated: the U C I measurements and Muse Spark calls are real. "
        "Fault scenarios, notifications and grid context are synthetic, and labelled so."),
    (6, "Measured results: the baseline reaches 1.293 megawatt-hours mean absolute error on the 2015 holdout. "
        "Four live Muse Spark cases passed validation with zero errors."),
    (10, "What the market lacks, in our view: monitoring exists, but not an evidence-linked investigation case "
         "with multi-agent cross-impact deliberation and an explicit autonomy policy."),
    (11, "Path to pilot: one turbine, one engineer, a read-only export, eight to twelve weeks in shadow mode, "
         "measuring engineer time, evidence correctness and acceptance."),
    (12, "Pushing the frontier: Meta Muse Spark reasons over a physical system through verifiable tools and a "
         "physics simulator, while a human makes every decision. ThermoMind."),
]
MIN_S, PAD_S, FPS, AR = 8.0, 0.6, 30, 48000


def run(*cmd):
    subprocess.run([str(c) for c in cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def tts(text: str, out: Path) -> float:
    import edge_tts
    mp3 = out.with_suffix(".mp3")
    for attempt in range(4):
        try:
            asyncio.run(edge_tts.Communicate(text, VOICE).save(str(mp3)))
            if mp3.stat().st_size > 1000:
                break
        except Exception:
            if attempt == 3:
                raise
    # trim edge-tts leading/trailing silence, normalise to 48 kHz stereo
    run("ffmpeg", "-y", "-i", mp3, "-af",
        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB,areverse",
        "-ar", AR, "-ac", 2, out)
    return duration(out)


def capture(slides, outdir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright
    shots = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        for n, _ in slides:
            pg.goto(f"file://{DECK}#{n}")
            pg.reload()  # hash-only navigation does not re-run show()
            pg.wait_for_load_state("networkidle")
            pg.evaluate("document.fonts.ready")
            pg.evaluate("document.querySelectorAll('.hint').forEach(e=>e.style.display='none')")
            pg.wait_for_timeout(400)
            p = outdir / f"slide_{n:02d}.png"
            pg.screenshot(path=str(p))
            shots.append(p)
        b.close()
    return shots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part-a", type=Path, default=ROOT / "submission/video/thermomind_demo_product_only.mp4")
    ap.add_argument("--out", type=Path, default=ROOT / "submission/video/thermomind_demo.mp4")
    ap.add_argument("--max-total", type=float, default=180.0)
    a = ap.parse_args()
    for t in SLIDES:
        assert len(t[1].split()) <= 30, (t[0], len(t[1].split()))
    tmp = Path(tempfile.mkdtemp(prefix="tm_final_"))
    shots = capture(SLIDES, tmp)
    segs = []
    for (n, text), img in zip(SLIDES, shots):
        wav = tmp / f"n_{n:02d}.wav"
        d = tts(text, wav)
        show = max(d + PAD_S, MIN_S)
        seg = tmp / f"seg_{n:02d}.mp4"
        run("ffmpeg", "-y", "-loop", 1, "-framerate", FPS, "-i", img, "-i", wav,
            "-filter_complex", f"[1:a]adelay=250|250,apad[a]", "-map", "0:v", "-map", "[a]",
            "-t", f"{show:.3f}", "-vf", "scale=1920:1080,format=yuv420p", "-r", FPS,
            "-c:v", "libx264", "-preset", "medium", "-crf", 18, "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k", "-ar", AR, "-ac", 2, seg)
        segs.append(seg)
        print(f"slide #{n}: {d:.1f} s speech -> {show:.1f} s on screen | {text}")
    # normalise PART A to identical parameters, then concat-filter everything (re-encode)
    inputs = [a.part_a] + segs
    args = ["ffmpeg", "-y"]
    for i in inputs:
        args += ["-i", i]
    fc = "".join(f"[{k}:v]scale=1920:1080,fps={FPS},format=yuv420p,setsar=1[v{k}];"
                 f"[{k}:a]aresample={AR},aformat=channel_layouts=stereo[a{k}];" for k in range(len(inputs)))
    fc += "".join(f"[v{k}][a{k}]" for k in range(len(inputs))) + f"concat=n={len(inputs)}:v=1:a=1[v][a]"
    tmp_out = tmp / "final.mp4"
    args += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
             "-crf", 20, "-pix_fmt", "yuv420p", "-r", FPS, "-c:a", "aac", "-b:a", "192k", "-ar", AR,
             "-movflags", "+faststart", tmp_out]
    run(*args)
    total = duration(tmp_out)
    print(f"total {total:.2f} s")
    if total > a.max_total:
        raise SystemExit(f"over {a.max_total} s: drop a slide from SLIDES and rerun")
    shutil.copy(tmp_out, a.out)
    print(json.dumps({"out": str(a.out), "duration": total}))


if __name__ == "__main__":
    main()
