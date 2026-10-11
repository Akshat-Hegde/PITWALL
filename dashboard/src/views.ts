import { useEffect, useRef, useState } from "react";
import type { TvSetting } from "./schema";

// What the TV shows. Two pages, LIVE and MULTIVIEW, chosen on /staff or with keys 1 / 2 on the TV PC (the
// newer choice wins, and it survives a reload). Nothing rotates while anyone drives. With nobody driving for
// IDLE_AFTER_MS the TV goes to attract mode (welcome and leaderboard), and back to the page when a car drives.
// Staff can put head to head or the team board over the page. Moments are overlays and never change it.

export type Page = "live" | "multi";
export type View = Page | "board" | "analysis" | "attract" | "teams" | "bracket";
/** ?view=...: fixes what the TV shows (for testing and screenshots); "auto" follows staff and idling. */
export type ViewMode = "auto" | View;

export const IDLE_AFTER_MS = 60_000; // nobody driving this long: attract mode
export const ATTRACT_HERO_MS = 20_000; // attract mode: the branded welcome screen this long...
export const ATTRACT_BOARD_MS = 20_000; // ...the leaderboard...
export const TEAMS_MS = 15_000; // ...the team leaderboard during a corporate event...
export const BRACKET_MS = 12_000; // ...and, in demo mode only, the tournament preview

/** Views that have something to show right now (and are switched on). */
export interface Available {
  analysis: boolean;
  attract?: boolean;
  teams?: boolean;
  bracket?: boolean;
}

const VIEWS: readonly View[] = ["live", "multi", "board", "analysis", "attract", "teams", "bracket"];
const PAGE_KEY = "simtelemetry-tv-page";

export function viewModeFromQuery(query: URLSearchParams): ViewMode {
  const v = query.get("view") as View | null;
  return v && VIEWS.includes(v) ? v : "auto";
}

/** A page chosen with the keys on the TV PC: kept in the browser, with when it was chosen. */
export interface LocalPage {
  page: Page;
  at: number;
}

/** The page to show: the newer of the staff's choice and a key press on the TV PC. */
export function currentPage(tv: TvSetting, local: LocalPage | null): Page {
  return local && local.at > tv.updated_at ? local.page : tv.page;
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
 */
export function chooseView(mode: ViewMode, page: Page, overlay: TvSetting["overlay"], idleForMs: number | null,
                           available: Available = { analysis: false }): { view: View; attract: boolean } {
  if (mode !== "auto") return { view: mode, attract: false };
  if (overlay === "head_to_head" && available.analysis) return { view: "analysis", attract: false };
  if (overlay === "teams" && available.teams) return { view: "teams", attract: false };
  if (idleForMs === null || idleForMs < IDLE_AFTER_MS || available.attract === false) {
    return { view: page, attract: false };
  }
  const schedule: [View, number][] = [];
  schedule.push(["attract", ATTRACT_HERO_MS]);
  schedule.push(["board", ATTRACT_BOARD_MS]);
  if (available.teams) schedule.push(["teams", TEAMS_MS]);
  if (available.bracket) schedule.push(["bracket", BRACKET_MS]);
  return { view: pick(schedule, idleForMs - IDLE_AFTER_MS), attract: true };
}

const KEYS: Record<string, Page> = { "1": "live", "2": "multi" };

function loadLocal(): LocalPage | null {
  try {
    const data = JSON.parse(localStorage.getItem(PAGE_KEY) ?? "null") as LocalPage | null;
    return data && (data.page === "live" || data.page === "multi") && typeof data.at === "number" ? data : null;
  } catch {
    return null;
  }
}

function saveLocal(local: LocalPage): void {
  try {
    localStorage.setItem(PAGE_KEY, JSON.stringify(local));
  } catch {
    // private mode or storage blocked: the choice lasts until the page reloads
  }
}

/** Current view; keys 1 / 2 on the TV PC pick LIVE / MULTIVIEW. */
export function useView(mode: ViewMode, anyDriving: boolean, available: Available, tv: TvSetting) {
  const [local, setLocal] = useState<LocalPage | null>(loadLocal);
  const [now, setNow] = useState(() => performance.now());
  const lastDriving = useRef<number>(performance.now());
  if (anyDriving) lastDriving.current = now;

  useEffect(() => {
    const timer = setInterval(() => setNow(performance.now()), 1000);
    const onKey = (e: KeyboardEvent) => {
      const page = KEYS[e.key];
      if (!page || e.ctrlKey || e.altKey || e.metaKey) return;
      const next = { page, at: Date.now() };
      saveLocal(next);
      setLocal(next);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearInterval(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const page = currentPage(tv, local);
  return { page, ...chooseView(mode, page, tv.overlay, anyDriving ? null : now - lastDriving.current, available) };
}
