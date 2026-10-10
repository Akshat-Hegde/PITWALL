import { formatDelta, formatLapTime } from "../format";
import type { DashboardState } from "../state/reducer";

const HOLDING_MS = 50; // last laps within this of each other: "holding"

export interface Battle {
  leader: { rigId: string; name: string; colour: string; bestMs: number };
  chaser: { rigId: string; name: string; colour: string; bestMs: number };
  gapMs: number;
  /** Chaser's last lap minus the leader's: negative = the chaser is catching. Null without both laps. */
  ratePerLapMs: number | null;
  /** Chaser's live delta to the leader's best lap at the same point on track. */
  liveMs: number | null;
}

/** The two closest cars on a track by best lap (works in Time Trial: compares best and last laps). */
export function findBattle(state: DashboardState, trackKey: string | null): Battle | null {
  if (!trackKey) return null;
  const cars = state.rigs
    .map((rig) => ({ rig, frame: state.frames[rig.rig_id] }))
    .filter(({ frame }) => frame?.session.track_key === trackKey && frame.state !== "no_data" && frame.best)
    .map(({ rig, frame }) => ({
      rigId: rig.rig_id,
      name: frame!.driver ?? rig.name,
      colour: rig.colour,
      bestMs: frame!.best!.lap_ms,
      lastMs: frame!.lap?.last_ms ?? null,
    }))
    .sort((a, b) => a.bestMs - b.bestMs);
  if (cars.length < 2) return null;
  let pair = [cars[0]!, cars[1]!];
  for (let i = 1; i < cars.length - 1; i++) {
    if (cars[i + 1]!.bestMs - cars[i]!.bestMs < pair[1]!.bestMs - pair[0]!.bestMs) pair = [cars[i]!, cars[i + 1]!];
  }
  const [leader, chaser] = pair as [(typeof cars)[0], (typeof cars)[0]];
  const live = state.comparison?.rigs.find((e) => e.rig_id === chaser.rigId && e.reference_rig_id === leader.rigId);
  return {
    leader,
    chaser,
    gapMs: chaser.bestMs - leader.bestMs,
    ratePerLapMs: leader.lastMs != null && chaser.lastMs != null ? chaser.lastMs - leader.lastMs : null,
    liveMs: live?.live_delta_ms ?? null,
  };
}

/** One line under the map: the closest pair, the gap, and whether it is closing (no box, DESIGN.md). */
export function BattleLine({ battle }: { battle: Battle }) {
  const rate = battle.ratePerLapMs;
  const trend = rate == null ? "none" : rate <= -HOLDING_MS ? "closing" : rate >= HOLDING_MS ? "opening" : "holding";
  const trendText =
    trend === "closing" ? `Closing ${(Math.abs(rate!) / 1000).toFixed(2)} s / lap`
      : trend === "opening" ? `Gap growing ${(rate! / 1000).toFixed(2)} s / lap`
        : trend === "holding" ? "Holding the gap" : "Trend after the next laps";
  return (
    <section className="battle" aria-label="Battle">
      <div className="battle__row">
        <span className="label">Battle</span>
        {[battle.leader, battle.chaser].map((d) => (
          <span key={d.rigId} className="battle__who" style={{ "--rig-colour": d.colour } as React.CSSProperties}>
            <span className="stripe" aria-hidden="true" />
            <span className="battle__name">{d.name}</span>
            <span className="battle__time">{formatLapTime(d.bestMs)}</span>
          </span>
        ))}
      </div>
      <div className="battle__row">
      <span className="battle__gap">{formatDelta(battle.gapMs)}</span>
      <span className={`battle__trend ${trend === "closing" ? "c-green" : trend === "opening" ? "c-yellow" : "t2"}`}>
        <span aria-hidden="true">{trend === "closing" ? "▼ " : trend === "opening" ? "▲ " : ""}</span>
        {trendText}
      </span>
      {battle.liveMs != null && (
        <span className="battle__live">
          <span className="label">This lap</span>
          <span className={battle.liveMs <= 0 ? "c-green" : "c-yellow"}>{formatDelta(battle.liveMs, 2)}</span>
        </span>
      )}
      </div>
    </section>
  );
}
