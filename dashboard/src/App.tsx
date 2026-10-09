import { useEffect } from "react";
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

/** Fastest best lap among rigs on the given track, or null. */
export function sessionBest(state: DashboardState, trackKey: string | null): number | null {
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
}

export function App({ store, mapDisplay = null, viewMode = "auto" }: Props) {
  const state = useDashboard(store);
  useBranding(state.cafe.branding);
  useEffect(() => {
    document.title = state.cafe.name ? `${state.cafe.name}: live timing` : "Live timing";
  }, [state.cafe.name]);
  const anyDriving = Object.values(state.frames).some((f) => f.state === "driving");
  const { view, mode, attract } = useView(viewMode, anyDriving);

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

  const trackKey = chooseTrackKey(state);
  return (
    <div className={`app app--${view}`}>
      <StatusBar state={state} viewNote={mode === "auto" ? (attract ? "Attract mode" : null) : `${view === "race" ? "Race" : "Leaderboard"} view (fixed)`} />
      {view === "race" ? (
        <RaceView store={store} state={state} trackKey={trackKey} mapDisplay={mapDisplay}
                  sessionBestMs={sessionBest(state, trackKey)} />
      ) : (
        <BoardView state={state} />
      )}
    </div>
  );
}
