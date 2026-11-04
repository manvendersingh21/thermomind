import { useCallback, useEffect, useState } from "react";

const KEY = "thermomind.persona";
export const DEFAULT_PERSONA = "reliability_engineer";
const EVT = "thermomind:persona";

export function getPersona(): string {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v) return v;
  } catch {
    /* storage unavailable */
  }
  return memoryPersona ?? DEFAULT_PERSONA;
}

let memoryPersona: string | null = null;

export function setPersonaValue(id: string): void {
  memoryPersona = id;
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new CustomEvent(EVT, { detail: id }));
}

/** [persona, setPersona]; synced across components and browser tabs. */
export function usePersona(): [string, (id: string) => void] {
  const [persona, setLocal] = useState<string>(() => getPersona());
  useEffect(() => {
    const sync = () => setLocal(getPersona());
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY || e.key === null) sync();
    };
    window.addEventListener(EVT, sync);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(EVT, sync);
      window.removeEventListener("storage", onStorage);
    };
  }, []);
  const set = useCallback((id: string) => setPersonaValue(id), []);
  return [persona, set];
}
