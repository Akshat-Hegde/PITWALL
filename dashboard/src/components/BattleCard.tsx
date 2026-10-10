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

export function BattleCard({ battle }: { battle: Battle }) {
  const rate = battle.ratePerLapMs;
  const trend = rate == null ? "none" : rate <= -HOLDING_MS ? "closing" : rate >= HOLDING_MS ? "opening" : "holding";
  const trendText =
    trend === "closing" ? `Catching by ${(Math.abs(rate!) / 1000).toFixed(2)} s per lap`
      : trend === "opening" ? `Gap growing by ${(rate! / 1000).toFixed(2)} s per lap`
        : trend === "holding" ? "Holding the gap" : "Trend after their next laps";
  return (
    <section className="battle" aria-label="Battle">
      <span className="label battle__title">Battle</span>
      {[battle.leader, battle.chaser].map((d, i) => (
        <div key={d.rigId} className="battle__row" style={{ "--rig-colour": d.colour } as React.CSSProperties}>
          <span className="battle__pos">{i + 1}</span>
          <span className="battle__name">{d.name}</span>
          <span className="battle__time">{formatLapTime(d.bestMs)}</span>
        </div>
      ))}
      <div className={`battle__gap battle__gap--${trend}`}>
        <span className="battle__gap-value">{formatDelta(battle.gapMs)}</span>
        <span className="battle__arrow" aria-hidden="true">
          {trend === "closing" ? "▼" : trend === "opening" ? "▲" : "■"}
        </span>
        <span className="battle__trend">{trendText}</span>
      </div>
      {battle.liveMs != null && (
        <span className="battle__live">
          Live on this lap <strong>{formatDelta(battle.liveMs, 2)}</strong>
        </span>
      )}
    </section>
  );
}
