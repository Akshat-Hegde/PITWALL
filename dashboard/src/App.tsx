import { useEffect } from "react";
import { ComparisonPanel } from "./components/ComparisonPanel";
import { LeaderboardPanel } from "./components/LeaderboardPanel";
import { RigPanel } from "./components/RigPanel";
import { StatusBar } from "./components/StatusBar";
import { TrackMap } from "./components/TrackMap";
import type { Display } from "./map/geometry";
import type { DashboardState } from "./state/reducer";
import { useDashboard, type DashboardStore } from "./state/store";

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
  return best;
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

export function App({ store, mapDisplay = null }: { store: DashboardStore; mapDisplay?: Display | null }) {
  const state = useDashboard(store);
  useBranding(state.cafe.branding);
  useEffect(() => {
    document.title = state.cafe.name ? `${state.cafe.name}: live timing` : "Live timing";
  }, [state.cafe.name]);

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
  const compact = state.rigs.length > 3;
  const sessionBestMs = sessionBest(state, trackKey);
  return (
    <div className="app">
      <StatusBar state={state} />
      <main className={`board${compact ? " board--many" : ""}`}>
        <section className="board__map" aria-label="Track map">
          <TrackMap store={store} state={state} trackKey={trackKey} displayOverride={mapDisplay} />
        </section>
        <section className="board__rigs" aria-label="Rigs">
          {state.rigs.length === 0 ? (
            <p className="panel__empty">Waiting for rigs. Start F1 with UDP telemetry on; rigs appear automatically.</p>
          ) : (
            state.rigs.map((rig, i) => (
              <RigPanel
                key={rig.rig_id}
                rig={rig}
                number={i + 1}
                frame={state.frames[rig.rig_id]}
                compact={compact}
                sessionBestMs={sessionBestMs}
              />
            ))
          )}
        </section>
        <ComparisonPanel comparison={state.comparison} rigs={state.rigs} />
        <LeaderboardPanel leaderboard={state.leaderboard} rigs={state.rigs} />
      </main>
    </div>
  );
}
