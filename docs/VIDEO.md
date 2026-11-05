# Demo video

The hackathon video is a scripted screen recording of the **running product** — real pages, real clicks,
stored real Meta Muse Spark output — with burned-in captions and a synthetic voice-over. It is produced by
one command, so it can be re-recorded whenever the UI changes.

| File | What |
|---|---|
| `submission/video/thermomind_demo.mp4` | the upload: 1920×1080 H.264 + AAC narration, ≤ 180 s |
| `submission/video/thermomind_demo_silent.mp4` | same picture, no audio track (captions only) |
| `submission/video/frames/*.png` | 3 stills for the README (overview, evidence drawer, propose / where-to-look) |
| `submission/video/chapters.txt` | YouTube chapter list (paste into the description) |
| `submission/video/narration_script.txt` | the exact caption / voice-over lines with their start times |
| `submission/video/markers.json` | segment start times (s) used for the audio placement |
| `submission/video/thermomind_live_investigation.mp4` | optional proof take of a NEW live Muse Spark run (`--live`) |

`raw/` (Playwright webm + session) and `narration/` (TTS clip cache) are git-ignored work files.

## Re-record

```bash
cd /root/thermomind && . .venv/bin/activate
pip install playwright==1.49.1 edge-tts && python -m playwright install --with-deps chromium   # once
apt-get install -y ffmpeg                                                                       # once
# backend + built UI on :8000, live S02 case case_76d34565b3dc present
python scripts/record_demo.py
```

Useful flags:

| Flag | Effect |
|---|---|
| `--dry-run` | drive the whole storyboard without recording; prints segment timings (fast selector check) |
| `--pace 0.9` | multiply every planned dwell by 0.9 (narration still gets clip + 0.5 s) |
| `--rate +15%` / `--voice en-GB-RyanNeural` | faster speech / other edge-tts voice (clips are cached per text+voice+rate) |
| `--no-narration` | captions only, no TTS / network |
| `--reuse-raw` | skip recording; re-encode / re-mux the last raw take (e.g. after changing the voice) |
| `--live` / `--live-only` | also / only record `thermomind_live_investigation.mp4`: starts a NEW live S02 run and waits (creates a stored case) |
| `--with-animation` | load the real educational-animation.org embeds instead of the labelled stub (slow under software rendering) |
| `--s02-case <id>` | use another stored `meta_live` S02 case |

If the run prints `FAIL: … > 180 s`, lower `--pace`, raise `--rate`, or shorten a line in `CAPTIONS`/`SPOKEN`
at the top of `scripts/record_demo.py` (all text and all dwell times live in two tables there).

## How it works

- Playwright Chromium (headless shell), viewport 1920×1080, `device_scale_factor=1`,
  `record_video_size=1920×1080`. Navigation is by real clicks on the sidebar links (client-side route change
  when a route has no sidebar link); scrolls and cursor glides are animated in-page so the 4-core recording box
  keeps up. A yellow cursor dot and a caption bar are injected (headless Chromium draws no OS cursor).
- Storyboard: [`docs/DEMO_SCRIPT.md`](DEMO_SCRIPT.md). Each segment starts with its caption; the segment lasts
  `max(planned dwell × pace, voice clip + 0.5 s)`, so picture and voice stay aligned.
- Voice-over: `edge-tts` (Microsoft neural voice `en-US-GuyNeural`, rate +8 %, no API key), one clip per
  segment, leading/trailing silence trimmed, written into a 48 kHz PCM track at the measured segment start
  times, then muxed: `ffmpeg -i silent.mp4 -i narration_track.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 160k -shortest`.
  The voice is synthetic; nothing claims to be a person.
- Video encode: `ffmpeg -ss <trim> -i take.webm -vf scale=1920:1080,fps=30 -c:v libx264 -crf 20 -preset veryfast -pix_fmt yuv420p -movflags +faststart`.
- The eval caption reads the real numbers from `GET /api/models/evaluation` at record time (holdout MAE 1.293 MWh
  vs 4.125 MWh naive previous-observation, 2015 holdout), matching `docs/EVALUATION.md`.
- Optional routes (`/twin/<case>`, `/propose`, `/autonomy`) are probed first; a route that is not
  served (the SPA redirects to `/`) is skipped together with its narration.

Honesty notes: the main take never starts a new Meta run — it opens the stored `meta_live` case
`case_76d34565b3dc` (S02, synthetic overlay, muse-spark-1.3). The third-party plant animation iframe is replaced
in the recording by a stub that says so ("loads here in the live app. Not rendered in this headless screen
recording."), because its WebGL load stalls software-rendered capture. No review is submitted on any case.

## Last measured take

Interim take on the UI as of 2026-11-04 20:35 UTC (routes `/twin`, `/propose`, `/autonomy` were not
served yet, so those segments were skipped; the final take will include them):

```
$ python scripts/record_demo.py
eval numbers from API: {'holdout_year': '2015', 'mae': '1.293', 'naive_mae': '4.125', 'mae_spoken': '1.29', 'naive_spoken': '4.13'}
  route /autonomy: NOT served -> segment skipped
  route /propose: NOT served -> segment skipped
  route /twin/case_76d34565b3dc: NOT served -> segment skipped
narration: 14 clips, 89.5 s of speech (voice en-US-GuyNeural, rate +8%)
wrote /root/thermomind/submission/video/thermomind_demo.mp4 (79.7 s, 14.6 MB) and thermomind_demo_silent.mp4

$ ffprobe -v error -show_entries format=duration,size,bit_rate:stream=index,codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt,sample_rate,channels -of default=noprint_wrappers=0 submission/video/thermomind_demo.mp4
[STREAM]
index=0
codec_name=h264
profile=High
codec_type=video
width=1920
height=1080
pix_fmt=yuv420p
r_frame_rate=30/1
[/STREAM]
[STREAM]
index=1
codec_name=aac
profile=LC
codec_type=audio
sample_rate=48000
channels=2
r_frame_rate=0/0
[/STREAM]
[FORMAT]
duration=79.666667
size=14580353
bit_rate=1464135
[/FORMAT]
```

Chapters of that take (`chapters.txt`): 0:00 Overview · 0:06 Live case S02 · 0:33 Where to look · 0:42 Inbox ·
0:51 Shift ops · 0:59 Evaluation & Trust · 1:13 ThermoMind.

## Upload checklist

1. Watch `thermomind_demo.mp4` end to end with sound: captions readable, voice aligned, no error banners, no
   personal data, duration ≤ 3:00 (`ffprobe` above).
2. YouTube → Create → Upload video → `thermomind_demo.mp4`. Title: "ThermoMind — evidence-first gas-turbine
   diagnostics with Meta Muse Spark (hackathon demo)". Description: one-paragraph summary, repo URL
   https://github.com/manvendersingh21/thermomind, the lines of `chapters.txt`, and "Voice-over is synthetic
   (Microsoft edge-tts). Data: UCI Gas Turbine CO and NOx Emission Data Set (CC BY 4.0); scenarios S02/S03 are
   synthetic overlays on copies of real rows."
3. Audience: "No, it's not made for kids". Visibility: **Unlisted** (or Public if the rules require it).
   Wait until HD processing finishes (1080p option visible).
4. Open the link in an **incognito window** (logged out): it plays, 1080p is selectable, sound is on.
5. Paste the link into the submission form and into `docs/SUBMISSION.md`.

## Final submission cut (product walkthrough + narrated slides)

Built by `scripts/make_final_video.py` (2026-11-05):

- **Part A** (0:00-1:20): the narrated product walkthrough above, unchanged. A copy is kept as
  `submission/video/thermomind_demo_product_only.mp4`.
- **Part B**: seven pitch-deck slides captured with Playwright at 1920×1080 from
  `submission/deck/index.html#N`, each narrated with edge-tts (`en-US-GuyNeural`, ≤ 30 words) and shown for
  max(clip + 0.6 s, 8 s): problem (#2), real-life use cases (#3), real vs simulated (#5), measured results
  (#6), what the market doesn't have (#10, stated as our hypothesis), path to pilot (#11), Push the Frontier
  (#12). Spoken numbers come only from `docs/EVALUATION.md` (1.293 MWh holdout MAE; 4 live Muse Spark cases,
  0 validation errors).
- A and B are joined with the ffmpeg concat filter and re-encoded to identical parameters (h264 yuv420p
  30 fps 1920×1080, aac 48 kHz stereo). The script refuses to write the output if it exceeds 180 s.

Rebuild: `. .venv/bin/activate && python scripts/make_final_video.py`
(Part A input defaults to `submission/video/thermomind_demo_product_only.mp4`).

## Motion-graphics explainer (`submission/video/thermomind_explainer.mp4`)

A separate ≤ 180 s explainer built from an animated HTML deck, not static slides.

- Source: `submission/explainer/index.html` (1920×1080, Inter, CSS keyframes + `requestAnimationFrame`; `?scene=N&dur=S`
  selects a scene and its length; the page sets `window.sceneReady` when the clock starts and `window.sceneDone` at the end).
- Scenes: 1 title (particles form a turbine outline) · 2 the problem (alarm cards are illustrative; counters are the real
  36,733 rows / 11 measurements / 0 fault labels) · 3 the loop (36,733 rows; holdout MAE 1.293 vs naive 12.957 MWh; 4 live
  cases, 0 validation errors) · 4 where to look (evidence drawer + 3D twin screenshots, LOOK HERE marker, synthetic S02) ·
  5 agents in collaboration (11 demo personas, example verdicts, human decides, nothing executed) · 6 physics simulator
  (SIMULATED; AFDP 3.9 → 17.6 mbar as in docs/FINAL_VERIFICATION.md) · 7 autonomy policy P-01 · 8 Push the Frontier,
  buyer, path to pilot, repo URL, honesty footer.
- Build: `scripts/make_explainer_video.py` records each scene with Playwright (chromium `--use-gl=angle
  --use-angle=swiftshader`, `record_video_dir`), trims the load pre-roll, narrates with edge-tts en-US-GuyNeural at -5 %
  (≤ 35 words per scene), shows each scene for max(narration + 0.8 s, 14 s), encodes h264 yuv420p 30 fps + aac 48 kHz and
  concatenates. It refuses to write output over 180 s.

Rebuild: `. .venv/bin/activate && python scripts/make_explainer_video.py`
