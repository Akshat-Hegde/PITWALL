import { useEffect, useState } from "react";
import type { Display } from "../map/geometry";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { BattleLine, findBattle } from "./Battle";
import { formatLapTime } from "../format";
import { LeaderboardPanel } from "./LeaderboardPanel";
import { ChallengeCard } from "./Competition";
import { StripeBundle, Tab } from "./Motifs";
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
        <TrackCard state={state} trackKey={trackKey} />
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

/** Track card (layout model from DESIGN.md motif 7): name, length in wide numerals, today's and all-time records. */
function TrackCard({ state, trackKey }: { state: DashboardState; trackKey: string | null }) {
  const session = Object.values(state.frames).find((f) => f.session.track_key === trackKey)?.session;
  const name = session?.track_name ?? state.leaderboards.today?.track_name ?? null;
  if (!name) return <div className="trackcard trackcard--empty" />;
  const km = session?.track_length_m ? (session.track_length_m / 1000).toFixed(3) : null;
  const sameTrack = (period: "today" | "all_time") => {
    const b = state.leaderboards[period];
    return b && b.track_key === trackKey ? b.entries[0] ?? null : null;
  };
  const today = sameTrack("today");
  const ever = sameTrack("all_time");
  return (
    <header className="trackcard">
      <div className="trackcard__name">
        <span className="label">{session?.session_type ?? "Track"}</span>
        <h1 className="trackcard__title">{name}</h1>
      </div>
      {km && (
        <div className="trackcard__stat">
          <span className="label">Length</span>
          <span className="trackcard__km">{km}<span className="unit">km</span></span>
        </div>
      )}
      {[["Today's record", today], ["Track record", ever]].map(([label, e]) => (
        e && typeof e === "object" ? (
          <div key={label as string} className="trackcard__stat">
            <span className="label">{label as string}</span>
            <span className="trackcard__record">
              <span className="c-purple">{formatLapTime(e.lap_ms)}</span>
              <span className="trackcard__holder">{e.driver ?? e.rig_name}</span>
            </span>
          </div>
        ) : null
      ))}
    </header>
  );
}

/** Open and Pro boards alternate on the leaderboard view (when there are Pro laps). */
export const BOARD_CLASS_MS = 15_000;

function useBoardClass(hasPro: boolean): "open" | "pro" {
  const [pro, setPro] = useState(false);
  useEffect(() => {
    if (!hasPro) {
      setPro(false);
      return;
    }
    const timer = setInterval(() => setPro((p) => !p), BOARD_CLASS_MS);
    return () => clearInterval(timer);
  }, [hasPro]);
  return pro && hasPro ? "pro" : "open";
}

/** Full-screen boards: today, this week, all time; Open and Pro alternate. */
export function BoardView({ state }: { state: DashboardState }) {
  const hasPro = Object.values(state.proLeaderboards).some((b) => b && b.entries.length > 0);
  const lapClass = useBoardClass(hasPro);
  const boards = lapClass === "pro" ? state.proLeaderboards : state.leaderboards;
  const track = state.leaderboards.today?.track_name ?? state.leaderboards.all_time?.track_name ?? null;
  return (
    <main className="boards">
      <StripeBundle corner="top-right" className="boards__stripes" />
      <header className="viewhead">
        <h1 className="viewhead__title">{track ?? "Best laps"}</h1>
        <Tab left={lapClass === "pro" ? "Pro" : "Open"}
             right={lapClass === "pro" ? "All assists off" : hasPro ? "All laps" : null} />
        <span className="viewhead__sub t2">Best lap per driver</span>
        <ChallengeCard state={state} compact />
      </header>
      <div className="boards__grid" key={lapClass}>
        <LeaderboardPanel title="Today" leaderboard={boards.today ?? null} rigs={state.rigs} showTrack={false} />
        <LeaderboardPanel title="This week" leaderboard={boards.week ?? null} rigs={state.rigs} showTrack={false} />
        <LeaderboardPanel title="All time" leaderboard={boards.all_time ?? null} rigs={state.rigs} showTrack={false} />
      </div>
    </main>
  );
}
