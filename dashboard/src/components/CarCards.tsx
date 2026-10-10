import { formatDelta, formatGear, formatLapTime, formatSector, formatSpeed } from "../format";
import type { ComparisonEntry, RigFrame, RigInfo, SectorTime } from "../schema";

const STATE_TEXT: Record<RigFrame["state"], string> = {
  driving: "On track",
  in_menu_paused: "In menu",
  no_data: "No data",
};

const REV_SEGMENTS = 15;
const DEFAULT_MAX_RPM = 13000;

interface Props {
  rigs: RigInfo[];
  frames: Record<string, RigFrame>;
  comparison: ComparisonEntry[];
  /** Today's fastest lap on the shown track: that best is purple, other bests green. */
  sessionBestMs: number | null;
}

/** One large live card per car (up to 4 rigs): speed, gear, revs, pedals, lap timing. */
export function CarCards({ rigs, frames, comparison, sessionBestMs }: Props) {
  const deltas = new Map(comparison.map((c) => [c.rig_id, c]));
  return (
    <section className="cards" aria-label="Cars">
      {rigs.map((rig, i) => (
        <CarCard
          key={rig.rig_id}
          rig={rig}
          number={i + 1}
          frame={frames[rig.rig_id]}
          delta={deltas.get(rig.rig_id)}
          sessionBestMs={sessionBestMs}
        />
      ))}
    </section>
  );
}

interface CardProps {
  rig: RigInfo;
  number: number;
  frame: RigFrame | undefined;
  delta: ComparisonEntry | undefined;
  sessionBestMs: number | null;
}

function CarCard({ rig, number, frame, delta, sessionBestMs }: CardProps) {
  const state = frame?.state ?? "no_data";
  const lap = frame?.lap ?? null;
  const driving = state === "driving";
  const bestMs = frame?.best?.lap_ms ?? null;
  const bestClass = bestMs == null ? "" : bestMs === sessionBestMs ? " is-session-best" : " is-personal-best";
  const live = delta?.live_delta_ms ?? null;
  const sectors: (SectorTime | null)[] = lap?.sectors ?? [null, null, null];
  return (
    <article
      className={`card card--${state.replace(/_/g, "-")}`}
      style={{ "--rig-colour": rig.colour } as React.CSSProperties}
      aria-label={`${rig.name}: ${frame?.driver ?? rig.name}, ${STATE_TEXT[state]}`}
    >
      <header className="card__head">
        <span className="card__badge">{number}</span>
        <span className="card__driver">{frame?.driver ?? rig.name}</span>
        <span className="card__meta">
          {frame?.driver && <span>{rig.name}</span>}
          {frame?.tyre && state !== "no_data" && (
            <span className={`card__tyre tyre--${frame.tyre.compound}`}>{frame.tyre.label}</span>
          )}
          {frame?.personal_best && state !== "no_data" && <span>PB {formatLapTime(frame.personal_best.lap_ms)}</span>}
        </span>
        <span className={`card__state${driving ? " is-live" : ""}`}>{STATE_TEXT[state]}</span>
      </header>

      {state === "no_data" ? (
        <p className="card__hint">
          Nothing received from {rig.address}. In F1 25 turn UDP telemetry on and drive in Time Trial.
        </p>
      ) : (
        <>
          <div className="card__live">
            <div className="card__speed">
              <span className="card__speed-value">{formatSpeed(driving ? frame?.speed_kph : null)}</span>
              <span className="card__unit">km/h</span>
            </div>
            <div className="card__gear" aria-label="Gear">{driving ? formatGear(frame?.gear) : "–"}</div>
            <div className="card__gauges">
              <RevBar rpm={driving ? frame?.rpm ?? null : null} maxRpm={frame?.max_rpm ?? null} />
              <Pedal label="Throttle" kind="throttle" value={driving ? frame?.throttle ?? null : null} />
              <Pedal label="Brake" kind="brake" value={driving ? frame?.brake ?? null : null} />
            </div>
          </div>

          <div className="card__timing">
            <div className="card__clock">
              <span className="card__label">{lap ? `Lap ${lap.number}` : "Lap"}</span>
              <span className={`card__clock-value${!lap ? " is-empty" : !lap.valid ? " is-invalid" : ""}`}>
                {formatLapTime(lap?.current_ms ?? null)}
              </span>
              {lap && !lap.valid && <span className="card__invalid">Invalid</span>}
            </div>
            <ol className="card__sectors" aria-label="Sectors">
              {[0, 1, 2].map((i) => {
                const s = sectors[i] ?? null;
                const rating = s ? (s.rating ?? "unrated") : lap && lap.sector === i ? "current" : "pending";
                return (
                  <li key={i} className={`csector csector--${rating.replace(/_/g, "-")}`}>
                    <span className="card__label">S{i + 1}</span>
                    <span className="csector__time">{formatSector(s?.ms ?? null)}</span>
                  </li>
                );
              })}
            </ol>
            <div className="card__stat">
              <span className="card__label">Last</span>
              <span className="card__stat-value">{formatLapTime(lap?.last_ms ?? null)}</span>
            </div>
            <div className="card__stat">
              <span className="card__label">Best</span>
              <span className={`card__stat-value${bestClass}`}>{formatLapTime(bestMs)}</span>
            </div>
            <div className="card__stat">
              <span className="card__label">Gap</span>
              <span className={`card__stat-value${live == null ? "" : live <= 0 ? " is-ahead" : " is-behind"}`}>
                {live == null ? "–" : formatDelta(live, 2)}
              </span>
            </div>
          </div>
        </>
      )}
    </article>
  );
}

function RevBar({ rpm, maxRpm }: { rpm: number | null; maxRpm: number | null }) {
  const max = maxRpm && maxRpm > 0 ? maxRpm : DEFAULT_MAX_RPM;
  const lit = rpm == null ? 0 : Math.round(Math.min(1, Math.max(0, rpm / max)) * REV_SEGMENTS);
  return (
    <div className="rev" aria-label={rpm == null ? "RPM unknown" : `${rpm} rpm`}>
      <div className="rev__bar">
        {Array.from({ length: REV_SEGMENTS }, (_, i) => (
          <span
            key={i}
            className={`rev__seg${i < lit ? " is-lit" : ""} rev__seg--${i < 9 ? "low" : i < 13 ? "mid" : "high"}`}
          />
        ))}
      </div>
      <span className="rev__value">{rpm == null ? "–" : rpm.toLocaleString("en-US")} rpm</span>
    </div>
  );
}

function Pedal({ label, kind, value }: { label: string; kind: "throttle" | "brake"; value: number | null }) {
  const pct = Math.round(Math.min(1, Math.max(0, value ?? 0)) * 100);
  return (
    <div className={`hpedal hpedal--${kind}`} aria-label={`${label} ${value == null ? "unknown" : `${pct}%`}`}>
      <span className="card__label">{label}</span>
      <span className="hpedal__track">
        <span className="hpedal__fill" style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}
