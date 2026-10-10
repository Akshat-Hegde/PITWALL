import type { Display } from "../map/geometry";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { BattleLine, findBattle } from "./Battle";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { Summary } from "./Summary";
import { MAX_CARDS, Timing, runningOrder } from "./Timing";
import { TrackMap } from "./TrackMap";

interface RaceProps {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  mapDisplay: Display | null;
  sessionBestMs: number | null;
}

/**
 * Race view: the map (coloured by the lead car's mini-sectors) with the closest battle underneath, the timing
 * (cards up to MAX_CARDS rigs, a tower above), and a strip with today's top three, speed trap and conditions.
 */
export function RaceView({ store, state, trackKey, mapDisplay, sessionBestMs }: RaceProps) {
  const order = runningOrder(state, trackKey);
  const focus = order.find(({ rig }) => state.frames[rig.rig_id]?.state === "driving")?.rig ?? null;
  const focusFrame = focus ? state.frames[focus.rig_id] : undefined;
  const battle = findBattle(state, trackKey);
  const hasOutline = trackKey ? Boolean(state.outlines[trackKey]) : false;
  return (
    <main className={`race race--${state.rigs.length <= MAX_CARDS ? "cards" : "tower"}`}>
      <section className="race__map" aria-label="Track map">
        <TrackMap store={store} state={state} trackKey={trackKey} displayOverride={mapDisplay}
                  focusRigId={focus?.rig_id ?? null} />
        {hasOutline && focus && (
          <div className="mapkey">
            <span className="label">
              Mini-sectors · {focusFrame?.driver ?? focus.name}
              {focusFrame?.lap ? ` · lap ${focusFrame.lap.number}` : ""}
            </span>
            <span className="mapkey__items">
              <span className="c-purple">Fastest</span>
              <span className="c-green">Personal best</span>
              <span className="c-yellow">Slower</span>
            </span>
          </div>
        )}
        {battle && <BattleLine battle={battle} />}
      </section>
      {state.rigs.length > 0 ? (
        <Timing store={store} state={state} trackKey={trackKey} sessionBestMs={sessionBestMs} />
      ) : (
        <section className="timing timing--empty">
          <h2 className="viewhead__title">No rigs yet</h2>
          <p className="t2">Each rig appears here as soon as its game sends telemetry.</p>
        </section>
      )}
      <Summary state={state} trackKey={trackKey} />
    </main>
  );
}

/** Full-screen boards: today, this week, all time. */
export function BoardView({ state }: { state: DashboardState }) {
  const track = state.leaderboards.today?.track_name ?? state.leaderboards.all_time?.track_name ?? null;
  return (
    <main className="boards">
      <header className="viewhead">
        <h1 className="viewhead__title">{track ?? "Best laps"}</h1>
        <span className="viewhead__sub t2">Best lap per driver</span>
      </header>
      <div className="boards__grid">
        <LeaderboardPanel title="Today" leaderboard={state.leaderboards.today ?? null} rigs={state.rigs}
                          showTrack={false} />
        <LeaderboardPanel title="This week" leaderboard={state.leaderboards.week ?? null} rigs={state.rigs}
                          showTrack={false} />
        <LeaderboardPanel title="All time" leaderboard={state.leaderboards.all_time ?? null} rigs={state.rigs}
                          showTrack={false} />
      </div>
    </main>
  );
}
