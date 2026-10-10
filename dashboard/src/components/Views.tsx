import type { Display } from "../map/geometry";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { CarPanels } from "./CarPanel";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { PodiumRow } from "./PodiumRow";
import { TimingStrip } from "./TimingStrip";
import { TrackMap } from "./TrackMap";

interface RaceProps {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  mapDisplay: Display | null;
  sessionBestMs: number | null;
}

/** Telemetry panels up to this many rigs (dial, revs, pedals, tyres per car); the compact strip above it. */
export const MAX_PANELS = 4;

/**
 * Race view: today's podium, speed trap and conditions across the top; the track map; and per car a
 * telemetry panel (up to MAX_PANELS rigs) or a compact timing-strip row (more rigs).
 */
export function RaceView({ store, state, trackKey, mapDisplay, sessionBestMs }: RaceProps) {
  const panels = state.rigs.length > 0 && state.rigs.length <= MAX_PANELS;
  const comparison = state.comparison?.rigs ?? [];
  return (
    <main className="race">
      <PodiumRow state={state} trackKey={trackKey} />
      <MapCard store={store} state={state} trackKey={trackKey} mapDisplay={mapDisplay} />
      <div className="race__side">
        {panels ? (
          <CarPanels store={store} rigs={state.rigs} frames={state.frames} comparison={comparison}
                     sessionBestMs={sessionBestMs} />
        ) : state.rigs.length > 0 ? (
          <TimingStrip rigs={state.rigs} frames={state.frames} comparison={comparison} sessionBestMs={sessionBestMs} />
        ) : (
          <section className="side-empty">
            <h2 className="side-empty__title">No rigs yet</h2>
            <p>Each rig appears here as soon as its game sends telemetry.</p>
          </section>
        )}
      </div>
    </main>
  );
}

function MapCard({ store, state, trackKey, mapDisplay }: Omit<RaceProps, "sessionBestMs">) {
  const frame = Object.values(state.frames).find((f) => f.session.track_key === trackKey);
  const session = frame?.session;
  const name = session?.track_name ?? state.leaderboards.today?.track_name ?? null;
  const length = session?.track_length_m ? `${(session.track_length_m / 1000).toFixed(3)} km` : null;
  const hasOutline = trackKey ? Boolean(state.outlines[trackKey]) : false;
  return (
    <section className="mapcard" aria-label="Track map">
      <TrackMap store={store} state={state} trackKey={trackKey} displayOverride={mapDisplay} />
      {name && (
        <header className="mapcard__head">
          <h1 className="mapcard__track">{name}</h1>
          <span className="mapcard__meta">
            {session?.session_type && <span>{session.session_type}</span>}
            {length && <span>{length}</span>}
          </span>
        </header>
      )}
      {hasOutline && (
        <ul className="mapcard__legend" aria-label="Sectors">
          <li className="legend legend--s1">Sector 1</li>
          <li className="legend legend--s2">Sector 2</li>
          <li className="legend legend--s3">Sector 3</li>
        </ul>
      )}
    </section>
  );
}

/** Full-screen boards: today, this week, all time. */
export function BoardView({ state }: { state: DashboardState }) {
  const track = state.leaderboards.today?.track_name ?? state.leaderboards.all_time?.track_name ?? null;
  return (
    <main className="boards">
      <header className="boards__head">
        <h1 className="boards__track">{track ?? "Best laps"}</h1>
        <span className="boards__sub">Best lap per driver</span>
      </header>
      <div className="boards__grid">
        <LeaderboardPanel className="boards__today" title="Today" leaderboard={state.leaderboards.today ?? null}
                          rigs={state.rigs} showTrack={false} />
        <LeaderboardPanel title="This week" leaderboard={state.leaderboards.week ?? null} rigs={state.rigs}
                          showTrack={false} />
        <LeaderboardPanel title="All time" leaderboard={state.leaderboards.all_time ?? null} rigs={state.rigs}
                          showTrack={false} />
      </div>
    </main>
  );
}
