import { formatDelta, formatLapTime } from "../format";
import type { RigFrame } from "../schema";
import type { DashboardState } from "../state/reducer";

export const WEATHER_TEXT: Record<string, string> = {
  clear: "Clear",
  light_cloud: "Light cloud",
  overcast: "Overcast",
  light_rain: "Light rain",
  heavy_rain: "Heavy rain",
  storm: "Storm",
};

/** Bottom strip of the race view: today's top three, the speed trap and the conditions. Text and hairlines only. */
export function Summary({ state, trackKey }: { state: DashboardState; trackKey: string | null }) {
  const board = state.leaderboards.today;
  const entries = board && board.track_key === trackKey ? board.entries.slice(0, 3) : [];
  const colour = new Map(state.rigs.map((r) => [r.rig_id, r.colour]));
  const onTrack = Object.values(state.frames).filter((f) => f.session.track_key === trackKey);
  const trap = onTrack
    .filter((f) => f.car?.top_speed_kph)
    .sort((a, b) => (b.car!.top_speed_kph ?? 0) - (a.car!.top_speed_kph ?? 0))[0];
  const trapRig = trap ? state.rigs.find((r) => r.rig_id === trap.rig_id) : undefined;
  return (
    <footer className="summary" aria-label="Today on this track">
      <div className="summary__group summary__today">
        <span className="label">Fastest today</span>
        {entries.length === 0 && <span className="t2">No clean laps yet</span>}
        {entries.map((e, i) => (
          <span key={`${e.rig_id}-${e.rank}`} className="summary__entry"
                style={{ "--rig-colour": colour.get(e.rig_id) ?? "var(--text-3)" } as React.CSSProperties}>
            <span className="summary__pos">{i + 1}</span>
            <span className="stripe" aria-hidden="true" />
            <span className="summary__name">{e.driver ?? e.rig_name}</span>
            <span className={i === 0 ? "c-purple" : ""}>{formatLapTime(e.lap_ms)}</span>
            {i > 0 && <span className="t2">{formatDelta(e.gap_ms)}</span>}
          </span>
        ))}
      </div>
      <div className="summary__group">
        <span className="label">Speed trap</span>
        <span className="summary__big">{trap ? trap.car!.top_speed_kph : "–"}</span>
        <span className="unit">km/h</span>
        {trap && <span className="t2">{trap.driver ?? trapRig?.name}</span>}
      </div>
      <Conditions frame={onTrack[0]} />
    </footer>
  );
}

function Conditions({ frame }: { frame: RigFrame | undefined }) {
  const s = frame?.session;
  const weather = s?.weather ?? null;
  return (
    <div className="summary__group">
      <span className="label">Conditions</span>
      <span>{weather ? WEATHER_TEXT[weather] ?? weather : "–"}</span>
      <span className="label">Air</span>
      <span className="summary__big">{s?.air_temp_c ?? "–"}°</span>
      <span className="label">Track</span>
      <span className="summary__big">{s?.track_temp_c ?? "–"}°</span>
    </div>
  );
}
