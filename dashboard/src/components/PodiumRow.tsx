import { formatDelta, formatLapTime } from "../format";
import type { RigFrame, RigInfo } from "../schema";
import type { DashboardState } from "../state/reducer";

const WEATHER_TEXT: Record<string, string> = {
  clear: "Clear",
  light_cloud: "Light cloud",
  overcast: "Overcast",
  light_rain: "Light rain",
  heavy_rain: "Heavy rain",
  storm: "Storm",
};

/** Today's top three, the speed trap and the conditions, across the top of the race view. */
export function PodiumRow({ state, trackKey }: { state: DashboardState; trackKey: string | null }) {
  const board = state.leaderboards.today;
  const entries = board && board.track_key === trackKey ? board.entries.slice(0, 3) : [];
  const colour = new Map(state.rigs.map((r) => [r.rig_id, r.colour]));
  const onTrack = Object.values(state.frames).filter((f) => f.session.track_key === trackKey);
  return (
    <section className="podium" aria-label="Today on this track">
      {[0, 1, 2].map((i) => {
        const e = entries[i];
        return (
          <article
            key={i}
            className={`pod pod--p${i + 1}${e ? "" : " pod--empty"}`}
            style={{ "--rig-colour": e ? colour.get(e.rig_id) ?? "var(--rule)" : "var(--rule)" } as React.CSSProperties}
          >
            <span className="pod__pos">P{i + 1}</span>
            {e ? (
              <div className="pod__body">
                <span className="pod__driver">{e.driver ?? e.rig_name}</span>
                <span className="pod__line">
                  <span className={`pod__time${i === 0 ? " is-purple" : ""}`}>{formatLapTime(e.lap_ms)}</span>
                  <span className="pod__gap">{i === 0 ? "Fastest today" : formatDelta(e.gap_ms)}</span>
                </span>
              </div>
            ) : (
              <div className="pod__body">
                <span className="pod__driver muted">Open</span>
                <span className="pod__gap">Set a clean lap to take it</span>
              </div>
            )}
          </article>
        );
      })}
      <SpeedTrap frames={onTrack} rigs={state.rigs} />
      <Conditions frame={onTrack[0]} />
    </section>
  );
}

function SpeedTrap({ frames, rigs }: { frames: RigFrame[]; rigs: RigInfo[] }) {
  const best = frames
    .filter((f) => f.car?.top_speed_kph)
    .sort((a, b) => (b.car!.top_speed_kph ?? 0) - (a.car!.top_speed_kph ?? 0))[0];
  const rig = best ? rigs.find((r) => r.rig_id === best.rig_id) : undefined;
  return (
    <article className="pod pod--stat" style={{ "--rig-colour": rig?.colour ?? "var(--rule)" } as React.CSSProperties}>
      <span className="pod__label">Speed trap</span>
      <span className="pod__big">
        {best ? best.car!.top_speed_kph : "–"}
        <span className="pod__unit">km/h</span>
      </span>
      <span className="pod__gap">{best ? (best.driver ?? rig?.name) : "Top speed this session"}</span>
    </article>
  );
}

function Conditions({ frame }: { frame: RigFrame | undefined }) {
  const s = frame?.session;
  const weather = s?.weather ?? null;
  return (
    <article className="pod pod--stat pod--weather">
      <span className="pod__label">{weather ? WEATHER_TEXT[weather] ?? weather : "Conditions"}</span>
      <div className="weather">
        <WeatherIcon kind={weather} />
        <div className="weather__temps">
          <span>
            <span className="pod__big pod__big--sm">{s?.air_temp_c ?? "–"}°</span>
            <span className="micro">Air</span>
          </span>
          <span>
            <span className="pod__big pod__big--sm">{s?.track_temp_c ?? "–"}°</span>
            <span className="micro">Track</span>
          </span>
        </div>
      </div>
    </article>
  );
}

function WeatherIcon({ kind }: { kind: string | null }) {
  const sun = kind === "clear" || kind === "light_cloud";
  const cloud = kind !== "clear";
  const rain = kind === "light_rain" || kind === "heavy_rain" || kind === "storm";
  return (
    <svg className="weather__icon" viewBox="0 0 48 48" aria-hidden="true">
      {sun && (
        <g className="wx-sun">
          <circle cx={cloud ? 18 : 24} cy={cloud ? 17 : 24} r="8" />
          {Array.from({ length: 8 }, (_, i) => {
            const a = (i * Math.PI) / 4;
            const cx = cloud ? 18 : 24;
            const cy = cloud ? 17 : 24;
            return (
              <line key={i} x1={cx + Math.cos(a) * 11} y1={cy + Math.sin(a) * 11} x2={cx + Math.cos(a) * 14}
                    y2={cy + Math.sin(a) * 14} />
            );
          })}
        </g>
      )}
      {cloud && kind && <path className="wx-cloud" d="M14 34h21a7 7 0 0 0 0-14 10 10 0 0 0-19 3 6 6 0 0 0-2 11z" />}
      {rain && (
        <g className="wx-rain">
          <line x1="18" y1="38" x2="16" y2="44" />
          <line x1="25" y1="38" x2="23" y2="44" />
          <line x1="32" y1="38" x2="30" y2="44" />
        </g>
      )}
    </svg>
  );
}
