import { formatDelta, formatGear, formatLapTime, formatSector } from "../format";
import type { ComparisonEntry, RigFrame, RigInfo, SectorTime } from "../schema";
import type { LapShare } from "../state/lapshare";
import type { DashboardStore } from "../state/store";
import { CarTopDown, SteeringWheel } from "./CarGraphics";
import { GForce, LapShareBars, Pedals, RevLights, SpeedDial, Systems } from "./Gauges";

const STATE_TEXT: Record<RigFrame["state"], string> = {
  driving: "Live",
  in_menu_paused: "In menu",
  no_data: "No data",
};

const COMPOUND_LETTER: Record<string, string> = { soft: "S", medium: "M", hard: "H", inter: "I", wet: "W" };

interface Props {
  store: DashboardStore;
  rigs: RigInfo[];
  frames: Record<string, RigFrame>;
  comparison: ComparisonEntry[];
  /** Today's fastest lap on the shown track: that best is purple, other bests green. */
  sessionBestMs: number | null;
}

/** One telemetry panel per car (up to 4 rigs). Two or fewer get the full layout. */
export function CarPanels({ store, rigs, frames, comparison, sessionBestMs }: Props) {
  const deltas = new Map(comparison.map((c) => [c.rig_id, c]));
  const compact = rigs.length > 2;
  return (
    <section className={`panels${compact ? " panels--grid" : ""}`} aria-label="Cars">
      {rigs.map((rig, i) => (
        <CarPanel
          key={rig.rig_id}
          rig={rig}
          number={i + 1}
          frame={frames[rig.rig_id]}
          delta={deltas.get(rig.rig_id)}
          sessionBestMs={sessionBestMs}
          compact={compact}
          share={store.lapShare.thisLap(rig.rig_id)}
          lastShare={store.lapShare.lastLap(rig.rig_id)}
          gTrail={store.gTrail.get(rig.rig_id) ?? []}
          steeringRotationDeg={store.getState().steeringRotationDeg}
        />
      ))}
    </section>
  );
}

interface PanelProps {
  rig: RigInfo;
  number: number;
  frame: RigFrame | undefined;
  delta: ComparisonEntry | undefined;
  sessionBestMs: number | null;
  compact: boolean;
  share: LapShare | null;
  lastShare: LapShare | null;
  gTrail: [number, number][];
  steeringRotationDeg: number;
}

function CarPanel({ rig, number, frame, delta, sessionBestMs, compact, share, lastShare, gTrail,
                    steeringRotationDeg }: PanelProps) {
  const state = frame?.state ?? "no_data";
  const driving = state === "driving";
  const lap = frame?.lap ?? null;
  const car = frame?.car ?? null;
  const bestMs = frame?.best?.lap_ms ?? null;
  const bestClass = bestMs == null ? "" : bestMs === sessionBestMs ? " is-purple" : " is-green";
  const live = delta?.live_delta_ms ?? null;
  const sectors: (SectorTime | null)[] = lap?.sectors ?? [null, null, null];
  const tyre = frame?.tyre ?? null;
  return (
    <article
      className={`panel2 panel2--${state.replace(/_/g, "-")}${compact ? " panel2--compact" : ""}`}
      style={{ "--rig-colour": rig.colour } as React.CSSProperties}
      aria-label={`${rig.name}: ${frame?.driver ?? rig.name}`}
    >
      <header className="panel2__head">
        <div className="panel2__pos">
          <span className="label">Rig</span>
          <span className="panel2__num">{number}</span>
        </div>
        <div className="panel2__who">
          <span className="label">Driver</span>
          <span className="panel2__driver">{frame?.driver ?? rig.name}</span>
          <span className="panel2__rig">
            {rig.name}
            {frame?.personal_best && <span>PB {formatLapTime(frame.personal_best.lap_ms)}</span>}
          </span>
        </div>
        {!compact && state !== "no_data" && <Systems car={car} inline />}
        {tyre && state !== "no_data" && (
          <span className={`compound compound--${tyre.compound}`} title={tyre.label}>
            <span className="compound__ring">{COMPOUND_LETTER[tyre.compound] ?? "?"}</span>
            <span className="compound__text">
              {tyre.label}
              {tyre.age_laps != null && (
                <span className="micro">{tyre.age_laps === 1 ? "1 lap" : `${tyre.age_laps} laps`}</span>
              )}
            </span>
          </span>
        )}
        <span className={`live-pill${driving ? " is-live" : ""}`}>
          {driving && <span className="live-pill__dot" />}
          {lap && driving ? `Lap ${lap.number}` : STATE_TEXT[state]}
        </span>
      </header>

      {state === "no_data" ? (
        <p className="panel2__hint">
          Nothing received from {rig.address}. In F1 25 turn UDP telemetry on and drive out in Time Trial.
        </p>
      ) : (
        <>
          <div className="panel2__body">
            <SpeedDial
              speed={driving ? frame?.speed_kph ?? null : null}
              gear={driving ? formatGear(frame?.gear) : "–"}
              colour={rig.colour}
            />
            <div className="panel2__mid">
              <RevLights pct={driving ? car?.rev_lights_pct ?? null : null} rpm={driving ? frame?.rpm ?? null : null} />
              <div className="panel2__controls">
                <Pedals throttle={driving ? frame?.throttle ?? null : null} brake={driving ? frame?.brake ?? null : null} />
                {compact && <Systems car={car} />}
              </div>
            </div>
            {!compact && <CarTopDown car={car} />}
            {!compact && (
              <div className="panel2__right">
                <div className="panel2__instruments">
                  <GForce lat={car?.g_lat ?? null} long={car?.g_long ?? null} trail={driving ? gTrail : []} />
                  <SteeringWheel steer={driving ? car?.steer ?? null : null} rotationDeg={steeringRotationDeg} />
                </div>
                <LapShareBars share={driving ? share : null} last={lastShare} />
              </div>
            )}
          </div>

          <footer className="panel2__timing">
            <div className="timing__clock">
              <span className="micro">{lap && !lap.valid ? "Lap invalid" : "Current lap"}</span>
              <span className={`timing__clock-value${!lap ? " is-empty" : !lap.valid ? " is-invalid" : ""}`}>
                {formatLapTime(lap?.current_ms ?? null)}
              </span>
            </div>
            <ol className="timing__sectors" aria-label="Sectors">
              {[0, 1, 2].map((i) => {
                const s = sectors[i] ?? null;
                const rating = s ? (s.rating ?? "unrated") : lap && lap.sector === i ? "current" : "pending";
                return (
                  <li key={i} className={`sec sec--${rating.replace(/_/g, "-")}`}>
                    <span className="micro">S{i + 1}</span>
                    <span className="sec__time">{formatSector(s?.ms ?? null)}</span>
                  </li>
                );
              })}
            </ol>
            <div className="timing__stat">
              <span className="micro">Last</span>
              <span className="timing__value">{formatLapTime(lap?.last_ms ?? null)}</span>
            </div>
            <div className="timing__stat">
              <span className="micro">Best</span>
              <span className={`timing__value${bestClass}`}>{formatLapTime(bestMs)}</span>
            </div>
            <div className="timing__stat">
              <span className="micro">Gap</span>
              <span className={`timing__value${live == null ? "" : live <= 0 ? " is-green" : " is-red"}`}>
                {live == null ? "–" : formatDelta(live, 2)}
              </span>
            </div>
          </footer>
        </>
      )}
    </article>
  );
}
