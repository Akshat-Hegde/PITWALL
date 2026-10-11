import { useEffect, useRef } from "react";
import { AnalysisView, chooseDuel } from "./components/Analysis";
import { AttractView, PortraitView } from "./components/Attract";
import { BattlePopups, MomentLayer } from "./components/Moments";
import { KineticType } from "./components/Motifs";
import { OnboardView, onboardRigs } from "./components/Onboard";
import { StatusBar } from "./components/StatusBar";
import { BoardView, RaceView } from "./components/Views";
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
}

const VIEW_NAME: Record<string, string> = {
  race: "Live timing", board: "Leaderboard", analysis: "Head to head", onboard: "Onboard", attract: "Welcome",
};

/** Broadcast wipe between views (~400 ms): accent panel with speed lines and the next view's name. */
function ViewWipe({ view }: { view: string }) {
  return (
    <div className="wipe" key={view} aria-hidden="true">
      <span className="wipe__panel" />
      <KineticType words={[VIEW_NAME[view] ?? view]} rows={1} className="wipe__word" />
    </div>
  );
}

export function App({ store, mapDisplay = null, viewMode = "auto", layout = "tv" }: Props) {
  const state = useDashboard(store);
  useBranding(state.cafe.branding);
  useEffect(() => {
    document.title = state.cafe.name ? `${state.cafe.name}: live timing` : "Live timing";
  }, [state.cafe.name]);
  const anyDriving = Object.values(state.frames).some((f) => f.state === "driving");
  // Until any rig has connected, keep the race view: its map explains how to set up the games.
  const nothingYet = state.rigs.length === 0;
  const trackKey = chooseTrackKey(state);
  const f = state.features;
  const available = {
    analysis: f.head_to_head && chooseDuel(state, store.laps, trackKey) !== null,
    onboard: f.onboard && onboardRigs(state).length > 0,
    attract: f.attract,
  };
  const { view, mode, attract } = useView(viewMode, anyDriving || nothingYet, available);
  const firstView = useRef(view);
  const viewChanged = useRef(false);
  if (view !== firstView.current) viewChanged.current = true; // no wipe when the page first loads

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
      <div className="app app--portrait">
        {f.portrait ? <PortraitView state={state} /> : (
          <div className="fullscreen-message"><h1>Portrait screen is switched off</h1></div>
        )}
        <MomentLayer store={store} state={state} />
      </div>
    );
  }

  return (
    <div className={`app app--${view}`}>
      <StatusBar state={state} trackKey={trackKey} view={view}
                 modeNote={mode !== "auto" ? "Fixed" : attract ? "Attract" : "Auto"} />
      <div className="app__view" key={view}>
        {view === "race" && (
          <RaceView store={store} state={state} trackKey={trackKey} mapDisplay={mapDisplay}
                    sessionBestMs={sessionBest(state, trackKey)} />
        )}
        {view === "board" && <BoardView state={state} />}
        {view === "analysis" && <AnalysisView store={store} state={state} trackKey={trackKey} />}
        {view === "onboard" && <OnboardView store={store} state={state} />}
        {view === "attract" && <AttractView state={state} />}
      </div>
      {viewChanged.current && <ViewWipe key={view} view={view} />}
      {view !== "attract" && <BattlePopups state={state} trackKey={trackKey} />}
      <MomentLayer store={store} state={state} />
    </div>
  );
}
