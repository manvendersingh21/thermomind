/** Shared state for TwinPage and TwinEmbed: data, playback, live ref, location. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_WINDOW, MAX_WINDOW, fillLive, sampleAt, useHistorian, useInvestigation, useTwinData, type TwinWindow } from "./data";
import { locateCase } from "./locate";
import { emptyLive, type EquipmentId, type LiveState } from "./types";

export type TwinMode = "window" | "historian";

export interface TwinControllerOptions {
  thermalDemo?: boolean;
}

export function useTwinController(caseId: string | undefined, opts: TwinControllerOptions = {}) {
  const { inv, error: invError, loading: invLoading } = useInvestigation(caseId);
  const [manualWindow, setManualWindow] = useState<TwinWindow | null>(null);
  const [thermalDemo, setThermalDemo] = useState(Boolean(opts.thermalDemo));
  const [mode, setMode] = useState<TwinMode>("window");

  // Reset the manual window whenever the case changes.
  useEffect(() => setManualWindow(null), [caseId]);

  const win: TwinWindow = useMemo(() => {
    if (manualWindow) return manualWindow;
    if (inv) return { year: inv.window.source_year, start: inv.window.start, end: inv.window.end };
    return DEFAULT_WINDOW;
  }, [manualWindow, inv]);

  const ready = !caseId || !invLoading;
  const data = useTwinData(ready ? inv : null, win, { thermalScenario: thermalDemo ? "T01_HOT_CONNECTION" : "none" });
  const n = data.series?.rows.length ?? 0;

  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [rate, setRate] = useState(4); // samples per second
  useEffect(() => setIndex(0), [win.year, win.start, win.end]);

  useEffect(() => {
    if (!playing || mode !== "window" || n < 2) return;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % n), 1000 / rate);
    return () => window.clearInterval(id);
  }, [playing, mode, n, rate]);

  const historian = useHistorian(mode === "historian");
  const histRow = historian.data?.rows[historian.data.rows.length - 1] ?? null;

  const live = useRef<LiveState>(emptyLive());
  const current = useMemo(() => {
    if (mode === "historian") {
      if (!histRow) return { row: null, v: {} as Record<string, number | null>, expectedTey: null, year: null as number | null };
      const v: Record<string, number | null> = {};
      for (const [k, val] of Object.entries(histRow)) if (!["replay_tick", "source_year", "row_index"].includes(k)) v[k] = val;
      return { row: histRow.row_index, v, expectedTey: null, year: histRow.source_year };
    }
    return { ...sampleAt(data.series, index), year: win.year };
  }, [mode, histRow, data.series, index, win.year]);

  useEffect(() => {
    // In historian mode the thermal series belongs to the selected window, so only use it when the row is inside.
    const thermal = mode === "historian" && current.year !== win.year ? null : data.thermal;
    fillLive(live.current, current.row, current.v, thermal, data.emissions);
  }, [current, data.thermal, data.emissions, mode, win.year]);

  const location = useMemo(
    () => locateCase(inv, data.thermal, data.emissions, data.series?.syntheticMeasures ?? []),
    [inv, data.thermal, data.emissions, data.series],
  );

  // Hover / selection / camera focus
  const [hovered, setHovered] = useState<{ id: EquipmentId; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<EquipmentId | null>(null);
  const [focus, setFocus] = useState<{ id: EquipmentId | null; nonce: number }>({ id: null, nonce: 0 });
  const flyTo = useCallback((id: EquipmentId | null) => setFocus((f) => ({ id, nonce: f.nonce + 1 })), []);
  const onHover = useCallback((id: EquipmentId | null, x: number, y: number) => setHovered(id ? { id, x, y } : null), []);

  const setWindow = useCallback((w: TwinWindow) => {
    const start = Math.max(0, Math.floor(w.start));
    const len = Math.max(2, Math.min(MAX_WINDOW, Math.floor(w.end - w.start)));
    setManualWindow({ year: w.year, start, end: start + len });
  }, []);

  return {
    caseId,
    inv,
    invError,
    invLoading,
    data,
    win,
    setWindow,
    resetWindow: () => setManualWindow(null),
    windowOverridden: manualWindow !== null,
    thermalDemo,
    setThermalDemo,
    mode,
    setMode,
    historian,
    index,
    setIndex,
    n,
    playing,
    setPlaying,
    rate,
    setRate,
    live,
    current,
    location,
    hovered,
    onHover,
    selected,
    setSelected,
    focus,
    flyTo,
  };
}

export type TwinController = ReturnType<typeof useTwinController>;
