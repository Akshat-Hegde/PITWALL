import type { Display } from "../map/geometry";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { TimingStrip } from "./TimingStrip";
import { TrackMap } from "./TrackMap";

interface RaceProps {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  mapDisplay: Display | null;
  sessionBestMs: number | null;
}

/** Large map, compact timing strip (head-to-head in its Δ column), and today's top 3 when there is room. */
export function RaceView({ store, state, trackKey, mapDisplay, sessionBestMs }: RaceProps) {
  const roomForBoard = state.rigs.length <= 5;
  return (
    <main className="race">
      <section className="race__map" aria-label="Track map">
        <TrackMap store={store} state={state} trackKey={trackKey} displayOverride={mapDisplay} />
      </section>
      <div className="race__side">
        <TimingStrip
          rigs={state.rigs}
          frames={state.frames}
          comparison={state.comparison?.rigs ?? []}
          sessionBestMs={sessionBestMs}
        />
        {roomForBoard && (
          <LeaderboardPanel
            className="race__top"
            title="Fastest today"
            leaderboard={state.leaderboards.today ?? null}
            rigs={state.rigs}
            slots={3}
            top
          />
        )}
      </div>
    </main>
  );
}

/** Full-screen boards: today, this week, all time. */
export function BoardView({ state }: { state: DashboardState }) {
  const track = state.leaderboards.today?.track_name ?? state.leaderboards.all_time?.track_name ?? null;
  return (
    <main className="boards">
      <h1 className="boards__track">{track ?? "Best laps"}</h1>
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
