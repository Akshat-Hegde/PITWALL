import { formatDelta, formatLapTime } from "../format";
import type { Leaderboard, RigInfo } from "../schema";

interface Props {
  leaderboard: Leaderboard | null;
  rigs: RigInfo[];
}

export function LeaderboardPanel({ leaderboard, rigs }: Props) {
  const colour = new Map(rigs.map((r) => [r.rig_id, r.colour]));
  const entries = leaderboard?.entries ?? [];
  return (
    <section className="panel board-lb" aria-label="Best laps">
      <h2 className="panel__title">
        Best laps
        {leaderboard?.track_name && <span className="panel__sub">{leaderboard.track_name}</span>}
      </h2>
      {entries.length === 0 ? (
        <p className="panel__empty">No valid laps yet. Times appear here after a clean lap.</p>
      ) : (
        <ol className="lb">
          {entries.map((e) => (
            <li
              key={`${e.rig_id}-${e.driver ?? ""}`}
              className={`lb__row${e.rank === 1 ? " lb__row--first" : ""}`}
              style={{ "--rig-colour": colour.get(e.rig_id) ?? "#888" } as React.CSSProperties}
            >
              <span className="lb__rank">{e.rank}</span>
              <span className="stripe" aria-hidden="true" />
              <span className="lb__who">
                <span className="lb__driver">{e.driver ?? e.rig_name}</span>
                <span className="lb__rig">{e.rig_name}</span>
              </span>
              <span className="lb__time num">{formatLapTime(e.lap_ms)}</span>
              <span className="lb__gap num">{e.rank === 1 ? "" : formatDelta(e.gap_ms)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
