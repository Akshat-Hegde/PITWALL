import { useEffect, useRef, useState } from "react";
import { AnalysisView, chooseDuel } from "./components/Analysis";
import { AttractView, PortraitView } from "./components/Attract";
import { CardQr } from "./components/CardQr";
import { BracketPreview, TeamsView } from "./components/Competition";
import { BattlePopups, MomentLayer } from "./components/Moments";
import { KineticType } from "./components/Motifs";
import { MultiviewPage } from "./components/Live";
import { PitwallPage } from "./components/Pitwall";
import { TvStage } from "./components/Stage";
import { StatusBar } from "./components/StatusBar";
import { BoardView } from "./components/Views";
import type { Display } from "./map/geometry";
import type { DashboardState } from "./state/reducer";
import { useDashboard, type DashboardStore } from "./state/store";
import { useView, type ViewMode } from "./views";

/** Track shown on the map: the one most driving rigs are on, else the first rig's track. */
export function chooseTrackKey(state: DashboardState): string | null {
  const counts = new Map<string, number>();
  for (const frame of Object.values(state.frames)) {
    const key = frame.session.track_key;
    if (!key) continue;
    counts.set(key, (counts.get(key) ?? 0) + (frame.state === "driving" ? 2 : 1));
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const [key, count] of counts) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  // Nobody on a track (e.g. attract mode with every rig in the menu): show the boards' track.
  return best ?? state.leaderboards.today?.track_key ?? Object.keys(state.outlines)[0] ?? null;
}

/**
 * The lap time shown purple in the strip: today's fastest lap on the track (top of the today board, the
 * same source as purple sectors), or the fastest rig best when no board for that track has arrived.
 */
export function sessionBest(state: DashboardState, trackKey: string | null): number | null {
  const today = state.leaderboards.today;
  if (today && today.track_key === trackKey && today.entries.length > 0) return today.entries[0]!.lap_ms;
  let best: number | null = null;
  for (const frame of Object.values(state.frames)) {
    const ms = frame.best?.lap_ms;
    if (ms == null || frame.session.track_key !== trackKey) continue;
    if (best === null || ms < best) best = ms;
  }
  return best;
}

/** During a corporate event, the company's colour replaces the brand accent. */
function useEventAccent(accent: string | null) {
  useEffect(() => {
    if (!accent) return;
    const root = document.documentElement;
    const before = root.style.getPropertyValue("--brand-accent");
    root.style.setProperty("--brand-accent", accent);
    return () => {
      if (before) root.style.setProperty("--brand-accent", before);
      else root.style.removeProperty("--brand-accent");
    };
  }, [accent]);
}

/** Apply cafe branding (CSS custom properties from the hub config) to :root. */
function useBranding(branding: Record<string, string>) {
  useEffect(() => {
    const root = document.documentElement;
    const applied = Object.entries(branding).filter(([key]) => key.startsWith("--"));
    for (const [key, value] of applied) root.style.setProperty(key, value);
    return () => {
      for (const [key] of applied) root.style.removeProperty(key);
    };
  }, [branding]);
}

interface Props {
  store: DashboardStore;
  mapDisplay?: Display | null;
  viewMode?: ViewMode;
  /** "portrait": the entrance-screen layout (/portrait). */
  layout?: "tv" | "portrait";
  /** Demo mode (?demo=1): adds the tournament preview to the rotation. */
  demo?: boolean;
}

const VIEW_NAME: Record<string, string> = {
  live: "Live", multi: "Multiview", board: "Leaderboard", analysis: "Head to head", attract: "Welcome",
  teams: "Teams", bracket: "Hotlap cup",
};

/** How long the wipe overlay stays mounted (its CSS animation is 420 ms). */
export const WIPE_MS = 600;

/** The view the wipe is showing, for WIPE_MS after each change (none when the page first loads). */
function useWipe(view: string): string | null {
  const [wipe, setWipe] = useState<string | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    setWipe(view);
    const timer = setTimeout(() => setWipe(null), WIPE_MS);
    return () => clearTimeout(timer);
  }, [view]);
  return wipe;
}

/** Broadcast wipe between views (~400 ms): accent panel with speed lines and the next view's name. */
function ViewWipe({ view }: { view: string }) {
  return (
    <div className="wipe" aria-hidden="true">
      <span className="wipe__panel" />
      <KineticType words={[VIEW_NAME[view] ?? view]} rows={1} className="wipe__word" />
    </div>
  );
}

export function App({ store, mapDisplay = null, viewMode = "auto", layout = "tv", demo = false }: Props) {
  const state = useDashboard(store);
  useBranding(state.cafe.branding);
  useEffect(() => {
    document.title = state.cafe.name ? `${state.cafe.name} · ${__PRODUCT_NAME__}` : __PRODUCT_NAME__;
  }, [state.cafe.name]);
  const anyDriving = Object.values(state.frames).some((f) => f.state === "driving");
  // Until any rig has connected, keep the race view: its map explains how to set up the games.
  const nothingYet = state.rigs.length === 0;
  const trackKey = chooseTrackKey(state);
  const f = state.features;
  const available = {
    analysis: f.head_to_head && chooseDuel(state, store.laps, trackKey) !== null,
    attract: f.attract,
    teams: f.events && state.competition.event !== null,
    bracket: demo,
  };
  const event = f.events ? state.competition.event : null;
  useEventAccent(event?.accent ?? null);
  const chosen = useView(viewMode, anyDriving || nothingYet, available, state.tv).view;
  const view = chosen === "multi" && !f.onboard ? "live" : chosen; // [features] onboard = the MULTIVIEW page
  const wipe = useWipe(view);

  if (state.link === "version_mismatch") {
    return (
      <div className="fullscreen-message" role="alert">
        <h1>Dashboard and hub versions don't match</h1>
        <p>
          The hub sends schema version {state.receivedVersion}; this dashboard reads version 1. Update the hub or
          the dashboard so both match, then reload this page.
        </p>
      </div>
    );
  }

  if (layout === "portrait") {
    return (
      <TvStage width={1080} height={1920}>
        <div className="app app--portrait">
          {f.portrait ? <PortraitView state={state} /> : (
            <div className="fullscreen-message"><h1>Portrait screen is switched off</h1></div>
          )}
          <CardQr state={state} />
          <MomentLayer store={store} state={state} />
        </div>
      </TvStage>
    );
  }

  return (
    <TvStage>
    <div className={`app app--${view}`}>
      {view !== "live" && <StatusBar state={state} trackKey={trackKey} />}
      {/* Keys are unique among siblings: one view is mounted at a time, whatever the transition. */}
      <div className="app__view" key={`view:${view}`}>
        {view === "live" && (
          <PitwallPage store={store} state={state} trackKey={trackKey} mapDisplay={mapDisplay}
                    pinnedRigId={state.tv.pinned_rig} />
        )}
        {view === "multi" && <MultiviewPage store={store} state={state} trackKey={trackKey} />}
        {view === "board" && <BoardView state={state} />}
        {view === "analysis" && <AnalysisView store={store} state={state} trackKey={trackKey} />}
        {view === "attract" && <AttractView state={state} />}
        {view === "teams" && <TeamsView state={state} />}
        {view === "bracket" && <BracketPreview />}
      </div>
      {wipe && <ViewWipe key={`wipe:${wipe}`} view={wipe} />}
      {view !== "attract" && <BattlePopups state={state} trackKey={trackKey} />}
      <CardQr state={state} />
      <MomentLayer store={store} state={state} />
    </div>
    </TvStage>
  );
}
