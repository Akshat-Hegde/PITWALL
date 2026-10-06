import { formatGear, formatLapTime, formatSector, formatSpeed } from "../format";
import type { RigFrame, RigInfo, SectorTime, Tyre } from "../schema";

const STATE_TEXT: Record<RigFrame["state"], string> = {
  driving: "On track",
  in_menu_paused: "In menu",
  no_data: "No data",
};

interface Props {
  rig: RigInfo;
  number: number;
  frame: RigFrame | undefined;
  compact: boolean;
  /** Fastest best lap of any rig on this track: purple; any other personal best is green. */
  sessionBestMs: number | null;
}

export function RigPanel({ rig, number, frame, compact, sessionBestMs }: Props) {
  const state = frame?.state ?? "no_data";
  const lap = frame?.lap ?? null;
  const bestMs = frame?.best?.lap_ms ?? null;
  const bestClass = bestMs == null ? "" : bestMs === sessionBestMs ? " is-session-best" : " is-personal-best";
  return (
    <article
      className={`rig rig--${state.replace(/_/g, "-")}${compact ? " rig--compact" : ""}`}
      style={{ "--rig-colour": rig.colour } as React.CSSProperties}
      aria-label={`${rig.name} timing`}
    >
      <header className="rig__head">
        <span className="rig__badge" aria-hidden="true">{number}</span>
        <div className="rig__who">
          <span className="rig__driver">{frame?.driver ?? rig.name}</span>
          {frame?.driver && <span className="rig__name">{rig.name}</span>}
        </div>
        <span className="rig__state">
          {lap && !lap.valid && <span className="rig__invalid">Lap invalid</span>}
          {state === "driving" && lap ? `Lap ${lap.number}` : STATE_TEXT[state]}
        </span>
      </header>

      {state === "no_data" ? (
        <p className="rig__hint">
          Nothing received from {rig.address}. Check the game is running with UDP telemetry on.
        </p>
      ) : (
        <>
          <div className="rig__main">
            <span
              className={`rig__current${lap && !lap.valid ? " is-invalid" : ""}`}
              aria-label={lap ? "Current lap time" : "Not on track"}
            >
              {lap ? formatLapTime(lap.current_ms) : formatLapTime(null)}
            </span>
            {!compact && (
              <div className="rig__car">
                <div className="rig__speed">
                  <span className="rig__speed-value">{formatSpeed(frame?.speed_kph)}</span>
                  <span className="rig__unit">km/h</span>
                </div>
                <div className="rig__gear" aria-label="Gear">{formatGear(frame?.gear)}</div>
                <Pedals throttle={frame?.throttle ?? null} brake={frame?.brake ?? null} />
              </div>
            )}
          </div>

          <ol className="sectors" aria-label="Sectors this lap">
            {[0, 1, 2].map((i) => (
              <SectorCell key={i} index={i} time={lap?.sectors[i] ?? null} active={lap?.sector === i} />
            ))}
          </ol>

          <div className="rig__foot">
            <dl className="rig__laps">
              <div>
                <dt>Last</dt>
                <dd>{formatLapTime(lap?.last_ms ?? null)}</dd>
              </div>
              <div>
                <dt>Best</dt>
                <dd className={`rig__best${bestClass}`}>{formatLapTime(bestMs)}</dd>
              </div>
            </dl>
            <TyreBadge tyre={frame?.tyre ?? null} />
          </div>
        </>
      )}
    </article>
  );
}

function SectorCell({ index, time, active }: { index: number; time: SectorTime | null; active: boolean }) {
  const rating = time?.rating ?? (time ? "unrated" : "pending");
  return (
    <li className={`sector sector--${rating.replace(/_/g, "-")}${active && !time ? " is-active" : ""}`}>
      <span className="sector__label">S{index + 1}</span>
      <span className="sector__time">{formatSector(time?.ms ?? null)}</span>
    </li>
  );
}

const COMPOUND_LETTER: Record<string, string> = { soft: "S", medium: "M", hard: "H", inter: "I", wet: "W" };

function TyreBadge({ tyre }: { tyre: Tyre | null }) {
  if (!tyre) return <div className="tyre tyre--unknown">–</div>;
  const letter = COMPOUND_LETTER[tyre.compound] ?? "?";
  return (
    <div className={`tyre tyre--${tyre.compound}`}>
      <span className="tyre__ring" aria-hidden="true">{letter}</span>
      <span className="tyre__text">
        <span className="tyre__label">{tyre.label}</span>
        {tyre.age_laps != null && (
          <span className="tyre__age">{tyre.age_laps === 1 ? "1 lap" : `${tyre.age_laps} laps`}</span>
        )}
      </span>
    </div>
  );
}

function Pedals({ throttle, brake }: { throttle: number | null; brake: number | null }) {
  const pct = (v: number | null) => `${Math.round(Math.min(1, Math.max(0, v ?? 0)) * 100)}%`;
  return (
    <div className="pedals" aria-label={`Throttle ${pct(throttle)}, brake ${pct(brake)}`}>
      <div className="pedal pedal--throttle">
        <span className="pedal__fill" style={{ height: pct(throttle) }} />
      </div>
      <div className="pedal pedal--brake">
        <span className="pedal__fill" style={{ height: pct(brake) }} />
      </div>
    </div>
  );
}
