import { formatDelta, formatGear, formatLapTime, formatSpeed } from "../format";
import type { ComparisonEntry, RigFrame, RigInfo, SectorTime } from "../schema";

const STATE_TEXT: Record<RigFrame["state"], string> = {
  driving: "On track",
  in_menu_paused: "In menu",
  no_data: "No data",
};

interface Props {
  rigs: RigInfo[];
  frames: Record<string, RigFrame>;
  comparison: ComparisonEntry[];
  /** Fastest best lap on the shown track: that best is purple, other bests green. */
  sessionBestMs: number | null;
}

/** One compact row per rig (up to 10 at 1080p). With three or fewer rigs rows are larger and show speed/gear. */
export function TimingStrip({ rigs, frames, comparison, sessionBestMs }: Props) {
  const roomy = rigs.length <= 3;
  const deltas = new Map(comparison.map((c) => [c.rig_id, c]));
  return (
    <section className={`strip${roomy ? " strip--roomy" : ""}`} aria-label="Timing">
      <div className="strip__head" aria-hidden="true">
        <span />
        <span>Driver</span>
        <span className="num">Lap</span>
        <span>Sectors</span>
        <span className="num">Last</span>
        <span className="num">Best</span>
        <span className="num">Δ</span>
        {roomy && <span className="num">Speed</span>}
      </div>
      {rigs.length === 0 ? (
        <p className="panel__empty">Waiting for rigs. Start F1 with UDP telemetry on; rigs appear automatically.</p>
      ) : (
        <ol className="strip__rows" style={{ "--slots": Math.max(rigs.length, roomy ? 3 : 5) } as React.CSSProperties}>
          {rigs.map((rig, i) => (
            <TimingRow
              key={rig.rig_id}
              rig={rig}
              number={i + 1}
              frame={frames[rig.rig_id]}
              delta={deltas.get(rig.rig_id)}
              sessionBestMs={sessionBestMs}
              roomy={roomy}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

interface RowProps {
  rig: RigInfo;
  number: number;
  frame: RigFrame | undefined;
  delta: ComparisonEntry | undefined;
  sessionBestMs: number | null;
  roomy: boolean;
}

function TimingRow({ rig, number, frame, delta, sessionBestMs, roomy }: RowProps) {
  const state = frame?.state ?? "no_data";
  const lap = frame?.lap ?? null;
  const bestMs = frame?.best?.lap_ms ?? null;
  const bestClass = bestMs == null ? "" : bestMs === sessionBestMs ? " is-session-best" : " is-personal-best";
  const live = delta?.live_delta_ms ?? null;
  const sectors: (SectorTime | null)[] = lap?.sectors ?? [null, null, null];
  return (
    <li
      className={`trow trow--${state.replace(/_/g, "-")}`}
      style={{ "--rig-colour": rig.colour } as React.CSSProperties}
      aria-label={`${rig.name}: ${frame?.driver ?? "no driver"}, ${STATE_TEXT[state]}`}
    >
      <span className="trow__badge">{number}</span>
      <span className="trow__who">
        <span className="trow__driver">{frame?.driver ?? rig.name}</span>
        <span className="trow__sub">
          {frame?.driver ? rig.name : rig.address}
          {frame?.tyre && state !== "no_data" && (
            <span className={`trow__tyre tyre--${frame.tyre.compound}`}>{frame.tyre.label}</span>
          )}
          {state !== "driving" && <span className="trow__state">{STATE_TEXT[state]}</span>}
          {lap && !lap.valid && <span className="trow__invalid">Invalid</span>}
        </span>
      </span>
      <span className={`trow__clock num${!lap ? " is-empty" : !lap.valid ? " is-invalid" : ""}`}>
        {lap ? formatLapTime(lap.current_ms) : formatLapTime(null)}
      </span>
      <span className="trow__sectors" aria-label="Sectors">
        {[0, 1, 2].map((i) => {
          const s = sectors[i] ?? null;
          const rating = s ? (s.rating ?? "unrated") : lap && lap.sector === i ? "current" : "pending";
          return <span key={i} className={`msector msector--${rating.replace(/_/g, "-")}`} title={`S${i + 1}`} />;
        })}
      </span>
      <span className="trow__last num">{formatLapTime(lap?.last_ms ?? null)}</span>
      <span className={`trow__best num${bestClass}`}>{formatLapTime(bestMs)}</span>
      <span className={`trow__delta num${live == null ? "" : live <= 0 ? " is-ahead" : " is-behind"}`}>
        {live == null ? "–" : formatDelta(live, 2)}
      </span>
      {roomy && (
        <span className="trow__speed num">
          {formatSpeed(frame?.speed_kph)}
          <span className="trow__gear">{formatGear(frame?.gear)}</span>
        </span>
      )}
    </li>
  );
}
