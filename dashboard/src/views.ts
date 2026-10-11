import { useEffect, useRef, useState } from "react";

export type View = "race" | "board" | "analysis" | "onboard" | "attract" | "teams" | "bracket";
/** What the TV is set to show: a fixed view, or "auto" (rotates while someone drives, attract mode otherwise). */
export type ViewMode = "auto" | View;

export const IDLE_AFTER_MS = 10_000; // nobody driving this long: attract mode
export const ATTRACT_HERO_MS = 20_000; // attract mode: the branded attract screen this long...
export const ATTRACT_BOARD_MS = 20_000; // ...the leaderboard view...
export const ATTRACT_RACE_MS = 10_000; // ...the race view (the track)...
export const ATTRACT_ANALYSIS_MS = 10_000; // ...and head to head (if there is one), repeating
export const LIVE_RACE_MS = 40_000; // someone driving: race view this long...
export const LIVE_ANALYSIS_MS = 15_000; // ...head to head (when two drivers have a full lap)...
export const LIVE_ONBOARD_MS = 15_000; // ...onboard...
export const TEAMS_MS = 15_000; // ...the team leaderboard during a corporate event...
export const BRACKET_MS = 12_000; // ...and, in demo mode only, the tournament preview

/** Views that have something to show right now (and are switched on). */
export interface Available {
  analysis: boolean;
  onboard: boolean;
  attract?: boolean;
  teams?: boolean;
  bracket?: boolean;
}

const NONE: Available = { analysis: false, onboard: false, attract: false };
const VIEWS: readonly View[] = ["race", "board", "analysis", "onboard", "attract", "teams", "bracket"];

export function viewModeFromQuery(query: URLSearchParams): ViewMode {
  const v = query.get("view") as View | null;
  return v && VIEWS.includes(v) ? v : "auto";
}

function pick(schedule: [View, number][], t: number): View {
  const total = schedule.reduce((s, [, ms]) => s + ms, 0);
  let left = ((t % total) + total) % total;
  for (const [view, ms] of schedule) {
    if (left < ms) return view;
    left -= ms;
  }
  return schedule[0]![0];
}

/**
 * idleForMs: time since a rig last drove (or since the page loaded); null while a rig is driving.
 * clockMs: a steady clock that drives the rotation while someone is driving.
 */
export function chooseView(mode: ViewMode, idleForMs: number | null, clockMs = 0,
                           available: Available = NONE): { view: View; attract: boolean } {
  if (mode !== "auto") return { view: mode, attract: false };
  if (idleForMs === null) {
    const schedule: [View, number][] = [["race", LIVE_RACE_MS]];
    if (available.analysis) schedule.push(["analysis", LIVE_ANALYSIS_MS]);
    if (available.onboard) schedule.push(["onboard", LIVE_ONBOARD_MS]);
    if (available.teams) schedule.push(["teams", TEAMS_MS]);
    if (available.bracket) schedule.push(["bracket", BRACKET_MS]);
    return { view: pick(schedule, clockMs), attract: false };
  }
  if (idleForMs < IDLE_AFTER_MS) return { view: "race", attract: false };
  const schedule: [View, number][] = [];
  if (available.attract) schedule.push(["attract", ATTRACT_HERO_MS]);
  schedule.push(["board", ATTRACT_BOARD_MS], ["race", ATTRACT_RACE_MS]);
  if (available.analysis) schedule.push(["analysis", ATTRACT_ANALYSIS_MS]);
  if (available.teams) schedule.push(["teams", TEAMS_MS]);
  if (available.bracket) schedule.push(["bracket", BRACKET_MS]);
  return { view: pick(schedule, idleForMs - IDLE_AFTER_MS), attract: true };
}

const KEYS: Record<string, ViewMode> = {
  "1": "race", "2": "board", "3": "analysis", "4": "onboard", "5": "attract", "6": "teams", "0": "auto", a: "auto",
};

/** Current view; keys 1-5 on the TV PC fix a view, 0 goes back to auto. */
export function useView(initialMode: ViewMode, anyDriving: boolean, available: Available) {
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

  return { mode, ...chooseView(mode, anyDriving ? null : now - lastDriving.current, now, available) };
}
