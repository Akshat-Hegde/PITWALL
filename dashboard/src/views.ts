import { useEffect, useRef, useState } from "react";

/** What the TV is set to show: a fixed view, or "auto" (race while someone drives, attract mode otherwise). */
export type ViewMode = "auto" | "race" | "board";
export type View = "race" | "board";

export const IDLE_AFTER_MS = 10_000; // nobody driving this long: attract mode
export const ATTRACT_BOARD_MS = 20_000; // attract mode: leaderboard view this long...
export const ATTRACT_RACE_MS = 10_000; // ...then race view (the track) this long, repeating

export function viewModeFromQuery(query: URLSearchParams): ViewMode {
  const v = query.get("view");
  return v === "race" || v === "board" ? v : "auto";
}

/** idleForMs: time since a rig last drove (or since the page loaded); null while a rig is driving. */
export function chooseView(mode: ViewMode, idleForMs: number | null): { view: View; attract: boolean } {
  if (mode !== "auto") return { view: mode, attract: false };
  if (idleForMs === null || idleForMs < IDLE_AFTER_MS) return { view: "race", attract: false };
  const t = (idleForMs - IDLE_AFTER_MS) % (ATTRACT_BOARD_MS + ATTRACT_RACE_MS);
  return { view: t < ATTRACT_BOARD_MS ? "board" : "race", attract: true };
}

const KEYS: Record<string, ViewMode> = { "1": "race", "2": "board", "0": "auto", a: "auto" };

/** Current view; keys 1 / 2 / 0 on the TV PC switch to race / leaderboard / auto. */
export function useView(initialMode: ViewMode, anyDriving: boolean) {
  const [mode, setMode] = useState<ViewMode>(initialMode);
  const [now, setNow] = useState(() => performance.now());
  const lastDriving = useRef<number>(performance.now());
  if (anyDriving) lastDriving.current = now;

  useEffect(() => {
    const timer = setInterval(() => setNow(performance.now()), 1000);
    const onKey = (e: KeyboardEvent) => {
      const next = KEYS[e.key.toLowerCase()];
      if (next && !e.ctrlKey && !e.altKey && !e.metaKey) setMode(next);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearInterval(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return { mode, ...chooseView(mode, anyDriving ? null : now - lastDriving.current) };
}
