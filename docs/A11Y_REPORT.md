# ThermoMind A11y / Responsive Audit

Date: 2026-11-04. Target: http://localhost:8000 (Chromium via Playwright). Report only; no source was edited.
Screenshots: `docs/screenshots/responsive/<route>_<width>.png` (28 files; routes: home, replay, investigations, case_76d34565b3dc, case_760658afb3d5, data, evaluation; widths 1440/1280/1024/390). All captured full-page.

## Method
- Each route loaded at 1440x900, 1280x800, 1024x768 and 390x844 (load event + 2.5 s settle).
- Horizontal overflow: `documentElement.scrollWidth > innerWidth`. "Biggest overflowers": elements whose bounding box extends past the viewport, or whose scrollWidth exceeds clientWidth with overflow-x visible, sorted by extent.
- Small text: computed `font-size` < 12 px for every visible text node's parent element (display/visibility/opacity/size filtered).
- Contrast: for text nodes, WCAG ratio of computed colour (alpha-composited) vs. the nearest opaque ancestor background (stacked semi-transparent layers composited on white). The 200 largest text nodes (by element area) were checked; flagged < 4.5:1 (3:1 for large text). Gradients/images are not resolved, and the WebGL twin canvas is not measured.
- Names: `<img>` without alt; `<svg>` outside button/link without aria-hidden/aria-label/title/role; button/a/input/select/textarea with no aria-label, labelledby, text, title or label.
- Focus order: click body, press Tab 15 times at 1440 (same list for all routes).
- Console: warning and error messages and page errors.

## Summary table (horizontal overflow: scrollWidth vs viewport)
| Route | 1440 | 1280 | 1024 | 390 |
|---|---|---|---|---|
| / | ok | ok | ok | 747 |
| /replay | ok | ok | ok | 674 |
| /investigations | ok | ok | ok | 484 |
| /investigations/case_76d34565b3dc | ok | ok | 1225 | 1225 |
| /investigations/case_760658afb3d5 | ok | ok | 1043 | 1043 |
| /data | 1554 | 1474 | 1346 | 1029 |
| /evaluation | ok | ok | ok | 702 |

Note: /investigations, /evaluation tables and the case-page tables are wider than their container at 1440 too, but are inside a scroll wrapper there (no page-level scroll), so it is acceptable on desktop.

## Prioritized fix list
1. **/data overflows the page at every width, including 1440 (1554 px).** Cause: `DIV.mx-auto max-w-[1400px] px-8 py-8` / `MAIN.min-w-0 flex-1` content is wider than its box (1298 vs 1184 at 1440). Tables (`table-base`, pages/DataSourcesPage.tsx lines ~85, 208, 232) have no `overflow-x-auto` wrapper, and `grid-cols-3`/`grid-cols-2`/`grid-cols-[180px_1fr]` (lines 75, 157, 160, 262) have no responsive breakpoints or `min-w-0`. Fix: wrap tables in `overflow-x-auto`, add `min-w-0` to grid children, use `grid-cols-1 md:grid-cols-3`.
2. **No responsive navigation: sidebar is a fixed `w-64 shrink-0` column (components/Layout.tsx:44).** At 390 px the content is squeezed and pages scroll sideways (home 747, replay 674, evaluation 702, investigations 484). Fix: collapse sidebar below `lg` into a top bar or hamburger drawer; ensure `main` has `min-w-0`.
3. **Case page (pages/InvestigationPage.tsx) overflows at <=1024 (1225/1043 px).** Biggest elements: a wide `table-base` (~1155 px wide at 390), and the closed `EvidenceDrawer` aside (520 px, right edge at viewport+520 when closed, components/EvidenceDrawer.tsx:73). Fix: scroll wrappers for tables, stack the page grid under `lg`.
4. **Closed EvidenceDrawer stays in the tab order / accessibility tree.** It is only hidden by `translate-x-full` with `role="dialog"`; no `inert`, `aria-hidden` or `visibility:hidden` when closed, no focus move on open or restore on close. Fix in components/EvidenceDrawer.tsx.
5. **Unnamed controls.**
   - /replay: `<input type="range" class="w-56 ...">` has no label (pages/ReplayPage.tsx:211). Add `aria-label="Replay position"`.
   - /investigations: 8 icon-only `<a>` links (SVG only) to `/investigations/<id>` (pages/InvestigationsPage.tsx). Add `aria-label`.
   - /data: hidden `input type=file` (pages/DataSourcesPage.tsx:127) has no name; add `aria-label` (it is `hidden`, so minor).
6. **Sub-12 px text.** `text-[11px]` sidebar group headings "Core", "Plant operations" (components/Layout.tsx) on every page; case pages have 56 / 42 small text nodes: "SYN" badges (`text-[11px]`, components/EvidenceChip.tsx and related), SVG labels in the plant schematic on home (11 px "fuel", "grid", "(to HRSG)"), and 3D labels (features/twin/scene/Labels.tsx). Raise to >= 12 px.
7. **Contrast below 4.5:1.**
   - Sidebar group headings "Core"/"Plant operations": 2.41:1 at 11 px (components/Layout.tsx). Worst offender.
   - `text-ink-400` body/mono text measures 4.47:1 (just under 4.5): footer/status lines "N points fetched ...", "No plant control actions are possible...", "Press Play to stream...", evaluation model names, `font-mono text-sm text-ink-400` on /data and /evaluation, "Generic educational combined-cycle plant" on case pages. Fix by darkening/lightening the `ink-400` token in the Tailwind config by a small amount (single-token fix clears most hits).
   - Sidebar footer "Diagnostic Intelligence", "v 0.1.0" (4.47:1).
   - Case pages at 390 px: 8 and 17 flagged text nodes (mostly `ink-400` mono 14 px, 4.47:1).
8. **Un-named SVGs.** Count of non-decorative SVGs with no label/role/title: home 12/36, replay 7/29, investigations 30/61, case pages 57/93 and 53/87, data 6/30, evaluation 18/34. Likely lucide icons (add `aria-hidden="true"`) and charts/schematics (add `role="img"` + `aria-label`). No `<img>` lacked alt (0 `img` without `alt` everywhere).
9. **Focus order / skip link.** Tab order on every page starts with the persona `<select aria-label="Switch demo persona">`, then 14 sidebar links (Overview, Replay, Investigations, Compare cases, Data Sources, Evaluation & Trust, Inbox, Ask the plant, Maintenance planner, Instrument health, Emissions watch, Thermal monitoring, Grid support, Shift ops). The first 15 tabs never reach page content; there is no skip-to-content link. Add one. Order itself is logical, and every one of the 15 had a visible outline/box-shadow.
10. **Console warnings (all routes).** Two React Router v6 future-flag warnings (`v7_startTransition`, `v7_relativeSplatPath`); set `future` flags on the router in src/main.tsx/App.tsx. Case pages additionally log a Chromium software WebGL fallback warning (headless-only; deprecated GPU fallback). No errors or pageerrors.

## Good
- `<html lang="en">`, single `<h1>`, `<main>` landmark on all routes; all images have alt; persona select and the drawer close button are labelled.

## Caveats
- Contrast uses solid backgrounds only (no gradient/canvas sampling); counts per page are of the 200 largest text nodes, not all.
- Full-page screenshot of the WebGL case pages is slow (several seconds); the first attempt timed out at 30 s and the run used a 15 s timeout with fallback, but all 28 shots came out `full`.
