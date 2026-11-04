#!/usr/bin/env python
"""Browser end-to-end smoke test + screenshots for the ThermoMind web UI.

Usage:
    . .venv/bin/activate
    python scripts/e2e_browser.py            # BASE defaults to http://localhost:8000
    BASE=http://localhost:5173 python scripts/e2e_browser.py

Visits /, /data, /evaluation, /replay, /investigations and the newest case page
(prefers a meta_live case), waits for network idle, collects console errors and
failed requests, asserts key copy is present, saves full-page screenshots to
docs/screenshots/, and exits non-zero on any failure. Playwright (chromium,
headless, 1440x900) is required: ``pip install playwright && python -m playwright
install chromium``.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

BASE = os.environ.get("BASE", "http://localhost:8000").rstrip("/")
REPO_ROOT = Path(__file__).resolve().parents[1]
SHOTS = REPO_ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}
NAV_TIMEOUT_MS = 60_000
TEXT_WAIT_MS = 20_000


def api_get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as resp:  # noqa: S310 - local demo server
        return json.loads(resp.read().decode("utf-8"))


def pick_cases() -> tuple[dict | None, dict | None]:
    """(newest case, preferring meta_live; newest *synthetic* case, preferring meta_live).

    The second is None when it would be the same case as the first."""
    try:
        cases = api_get("/api/investigations")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not list investigations: {type(exc).__name__}: {exc}")
        return None, None
    if not cases:
        return None, None
    live = [c for c in cases if c.get("mode") == "meta_live" and c.get("report")]
    primary = (live or cases)[0]
    synth = [c for c in cases if c.get("scenario_label") == "synthetic_overlay" and c.get("report")]
    synth_live = [c for c in synth if c.get("mode") == "meta_live"]
    secondary = (synth_live or synth or [None])[0]
    if secondary is not None and secondary["case_id"] == primary["case_id"]:
        secondary = None
    return primary, secondary


class PageCheck:
    def __init__(self, name: str, path: str, must_contain: list[str], ci: bool = False):
        self.name, self.path, self.must_contain, self.ci = name, path, must_contain, ci
        self.console_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.missing_text: list[str] = []
        self.error: str | None = None

    @property
    def ok(self) -> bool:
        return not (self.console_errors or self.failed_requests or self.missing_text or self.error)


def run_check(context, check: PageCheck, extra=None) -> None:
    page = context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)

    def on_console(msg):
        if msg.type == "error":
            check.console_errors.append(f"{msg.text} @ {msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}")

    def on_page_error(err):
        check.console_errors.append(f"uncaught: {err}")

    def on_request_failed(req):
        check.failed_requests.append(f"{req.method} {req.url} -> {req.failure}")

    def on_response(resp):
        if resp.status >= 400:
            check.failed_requests.append(f"{resp.request.method} {resp.url} -> HTTP {resp.status}")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)
    try:
        page.goto(f"{BASE}{check.path}", wait_until="networkidle")
        page.wait_for_timeout(750)  # let charts finish their first paint
        # React may still be rendering fetched data after network idle on a loaded machine:
        # poll the rendered text for up to TEXT_WAIT_MS before declaring copy missing.
        deadline = time.monotonic() + TEXT_WAIT_MS / 1000
        while True:
            text = page.locator("body").inner_text()
            hay = text.lower() if check.ci else text
            missing = [n for n in check.must_contain
                       if not any((a.lower() if check.ci else a) in hay for a in n.split("|"))]
            if not missing or time.monotonic() > deadline:
                break
            page.wait_for_timeout(500)
        check.missing_text = missing
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{check.name}.png"), full_page=True)
        if extra is not None:
            extra(page, check)
    except PlaywrightError as exc:
        check.error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
    finally:
        page.close()


def open_evidence_drawer(page, check: PageCheck) -> None:
    """Click the first element whose own text starts with ev_ and screenshot the drawer."""
    loc = page.get_by_text(re.compile(r"^ev_[a-z0-9_]+_\d+$", re.I)).first
    try:
        count = loc.count()
    except PlaywrightError:
        count = 0
    if count == 0:
        print("  - no element matching /^ev_/ found; evidence_drawer.png skipped")
        return
    try:
        loc.scroll_into_view_if_needed()
        loc.click()
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SHOTS / "evidence_drawer.png"), full_page=True)
        print(f"  - evidence drawer opened via '{loc.inner_text()[:40]}' -> evidence_drawer.png")
    except PlaywrightError as exc:
        print(f"  - could not open evidence drawer: {str(exc).splitlines()[0][:200]}")


def main() -> int:
    print(f"ThermoMind browser e2e against {BASE}")
    try:
        health = api_get("/api/health")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: backend not reachable at {BASE}: {exc}")
        return 2
    print(f"  health: status={health.get('status')} data_ready={health.get('data_ready')} "
          f"model_ready={health.get('model_ready')} meta_configured={health.get('meta_configured')}")

    case, synth_case = pick_cases()
    case_id = case["case_id"] if case else None
    case_synthetic = bool(case and case.get("scenario_label") == "synthetic_overlay")
    for label, c in (("case", case), ("synthetic case", synth_case)):
        if c:
            print(f"  {label}: {c['case_id']} mode={c.get('mode')} status={c.get('status')} "
                  f"scenario={c['scenario']['scenario_id']} synthetic={c.get('scenario_label') == 'synthetic_overlay'}")
    if not case:
        print("  ! no investigations found; case page check will be skipped")

    checks = [
        PageCheck("home", "/", ["ThermoMind"]),
        PageCheck("data", "/data", ["CC BY|CC-BY|UCI"]),
        PageCheck("evaluation", "/evaluation", ["MAE"]),
        PageCheck("replay", "/replay", ["ThermoMind"]),
        PageCheck("investigations", "/investigations", ["ThermoMind"]),
    ]
    case_check = None
    if case_id:
        needles = ["human review"] + (["synthetic"] if case_synthetic else [])
        case_check = PageCheck("investigation", f"/investigations/{case_id}", needles, ci=True)
        checks.append(case_check)
    if synth_case:
        checks.append(PageCheck("investigation_synthetic", f"/investigations/{synth_case['case_id']}",
                                ["human review", "synthetic"], ci=True))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        for check in checks:
            print(f"- {check.path}")
            run_check(context, check, extra=open_evidence_drawer if check is case_check else None)
            print(f"  {'OK ' if check.ok else 'FAIL'} console_errors={len(check.console_errors)} "
                  f"failed_requests={len(check.failed_requests)} missing_text={check.missing_text or '[]'}"
                  + (f" error={check.error}" if check.error else ""))
            for line in check.console_errors:
                print(f"    console: {line[:400]}")
            for line in check.failed_requests:
                print(f"    request: {line[:400]}")
        browser.close()

    failures = [c for c in checks if not c.ok]
    print()
    print(f"screenshots in {SHOTS}: {', '.join(sorted(f.name for f in SHOTS.glob('*.png')))}")
    print(f"summary: {len(checks) - len(failures)}/{len(checks)} pages OK"
          + (f"; FAILED: {', '.join(c.path for c in failures)}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
