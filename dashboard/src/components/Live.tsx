import { useEffect, useId, useRef } from "react";
import { formatDelta, formatGear, formatLapTime, formatSpeed } from "../format";
import type { RigFrame, RigInfo } from "../schema";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { FitText } from "./Stage";
import { TrackMap } from "./TrackMap";

// MULTIVIEW (one tile per active rig) and the pieces the LIVE page (Pitwall.tsx) shares with it: which rigs
// are active, which rig is on the hottest lap, the steering wheel and pedal bars. Needles are drawn every
// animation frame from the dashboard's live telemetry, interpolated between the 15 Hz frames.

/** The auto-selected rig in the strip changes at most this often. */
export const STRIP_HOLD_MS = 8_000;

/** Rigs shown on the TV: the ones the hub has data from (silent rigs are on the staff page only). */
export function activeRigs(state: DashboardState): RigInfo[] {
  return state.rigs.filter((r) => (state.frames[r.rig_id]?.state ?? "no_data") !== "no_data");
}

/**
 * The rig for the trace strip: the staff's pinned rig if it is active, else the rig on the fastest lap (its
 * best plus its live delta, i.e. the lap time it is on course for), else the fastest best lap, else the first
 * rig driving.
 */
export function chooseStripRig(state: DashboardState, store: DashboardStore, pinned: string | null): string | null {
  const active = activeRigs(state);
  if (pinned && active.some((r) => r.rig_id === pinned)) return pinned;
  const driving = active.filter((r) => state.frames[r.rig_id]?.state === "driving");
  let best: { id: string; ms: number } | null = null;
  for (const r of driving) {
    const f = state.frames[r.rig_id]!;
    const traces = store.live.speedTraces(r.rig_id);
    const delta = store.live.deltaToBest(r.rig_id);
    if (traces?.bestMs == null || delta == null || !f.lap) continue;
    const ms = traces.bestMs + delta;
    if (!best || ms < best.ms) best = { id: r.rig_id, ms };
  }
  if (best) return best.id;
  const byBest = driving
    .map((r) => ({ id: r.rig_id, ms: state.frames[r.rig_id]?.best?.lap_ms ?? Infinity }))
    .sort((a, b) => a.ms - b.ms);
  return byBest[0]?.id ?? active[0]?.rig_id ?? null;
}

/** Keeps an automatically chosen value for at least holdMs, so the strip doesn't flick between rigs. */
export function useHeld<T>(value: T, holdMs: number, now: number): T {
  const held = useRef<{ value: T; since: number }>({ value, since: now });
  if (value !== held.current.value && (now - held.current.since >= holdMs || held.current.value == null)) {
    held.current = { value, since: now };
  }
  return held.current.value;
}

function useRaf(draw: (now: number) => void) {
  const ref = useRef(draw);
  ref.current = draw;
  useEffect(() => {
    let id = 0;
    const loop = (t: number) => {
      ref.current(t);
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, []);
}

function rigStyle(rig: RigInfo): React.CSSProperties {
  return { "--rig-colour": rig.colour } as React.CSSProperties;
}

function deltaClass(ms: number | null): string {
  if (ms == null) return "delta delta--none";
  return ms < 0 ? "delta delta--ahead" : ms > 0 ? "delta delta--behind" : "delta";
}

/** The lap time on screen, and whether the lap still counts. */
function LapClock({ frame }: { frame: RigFrame | undefined }) {
  const lap = frame?.lap;
  const driving = frame?.state === "driving";
  return (
    driving && lap ? (
      <span className={`lapclock${!lap.valid ? " is-invalid" : ""}`}>{formatLapTime(lap.current_ms)}</span>
    ) : (
      <span className="lapclock lapclock--state">{STATE_TEXT[frame?.state ?? "no_data"] ?? "–"}</span>
    )
  );
}

const STATE_TEXT: Record<string, string> = { driving: "On track", in_menu_paused: "In menu", no_data: "Waiting" };

/** Formula-style wheel, drawn by us in a light colour that stands out on the dark TV: two grips, a carbon
 *  centre plate, a rev-light strip, a screen with the gear, coloured buttons and three rotary dials. */
const GRIP_L = "M-34 -22 C-44 -26 -50 -18 -50 -6 C-50 8 -47 22 -42 30 C-39 34 -33 33 -32 27 L-30 6 Z";
const GRIP_R = "M34 -22 C44 -26 50 -18 50 -6 C50 8 47 22 42 30 C39 34 33 33 32 27 L30 6 Z";
const PLATE = "M-34 -24 Q-34 -31 -27 -31 H27 Q34 -31 34 -24 V14 Q34 20 28 22 L16 27 Q12 29 8 29 H-8 Q-12 29 -16 27 " +
  "L-28 22 Q-34 20 -34 14 Z";
/** Rev lights across the top, lit from both ends inwards: green, red, then purple at the limit. */
const LED_X = Array.from({ length: 12 }, (_, i) => -16.5 + i * 3);
const LED_ORDER = [0, 11, 1, 10, 2, 9, 3, 8, 4, 7, 5, 6];
const LED_COLOUR = (rank: number) => (rank < 4 ? "#38d97a" : rank < 8 ? "#ff3b30" : "#b46cff");
const BUTTONS: [number, number, string][] = [
  [-27, -20, "#FFD43B"], [-27, -13, "#9B6BFF"], [-27, 4, "#FFFFFF"], [-27, 12, "#2A2D35"],
  [27, -20, "#FFD43B"], [27, -13, "#9B6BFF"], [27, 4, "#FFFFFF"], [27, 12, "#2A2D35"],
];
const DIALS: [number, string][] = [[-10, "#FFD43B"], [0, "#5B8CFF"], [10, "#2EC4B6"]];

/** A formula-style steering wheel that turns with the driver's input: rev LEDs, the gear on its screen, and
 *  the angle in degrees under it. */
export function SteeringWheel({ store, rigId, frameHz, rotationDeg, frame }: {
  store: DashboardStore; rigId: string; frameHz: number; rotationDeg: number; frame?: RigFrame;
}) {
  const wheel = useRef<SVGGElement>(null);
  const label = useRef<HTMLSpanElement>(null);
  useRaf((now) => {
    const s = store.live.inputAt(rigId, now - 1000 / frameHz);
    const deg = (s?.steer ?? 0) * (rotationDeg / 2);
    if (wheel.current) wheel.current.setAttribute("transform", `rotate(${deg.toFixed(1)})`);
    if (label.current) {
      const r = Math.round(deg);
      const text = `${r < 0 ? "−" : ""}${Math.abs(r)}°`;
      if (label.current.textContent !== text) label.current.textContent = text;
    }
  });
  const driving = frame?.state === "driving";
  const revs = driving ? frame?.car?.rev_lights_pct ?? null : null;
  const lit = revs == null ? 0 : Math.round((Math.max(0, Math.min(100, revs)) / 100) * LED_X.length);
  const gear = driving ? formatGear(frame?.gear) : "";
  const carbon = `wheel-carbon-${useId().replace(/:/g, "")}`;
  return (
    <div className="wheel">
      <svg className="wheel__svg" viewBox="-52 -52 104 104" aria-hidden="true">
        <defs>
          <pattern id={carbon} width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="3" height="3" fill="#D3D6DD" />
            <rect width="1.5" height="1.5" fill="#BFC3CB" />
            <rect x="1.5" y="1.5" width="1.5" height="1.5" fill="#BFC3CB" />
          </pattern>
        </defs>
        <g ref={wheel} className="wheel__turn">
          <path className="wheel__grip" d={GRIP_L} />
          <path className="wheel__grip" d={GRIP_R} />
          <path className="wheel__plate" d={PLATE} fill={`url(#${carbon})`} />
          {LED_X.map((x, i) => {
            const rank = LED_ORDER.indexOf(i);
            return <circle key={i} cx={x} cy={-27.5} r={1.15} fill={rank < lit ? LED_COLOUR(rank) : "#6C717D"} />;
          })}
          <rect className="wheel__screen" x="-15" y="-23" width="30" height="20" rx="1.5" />
          <rect x="-13" y="-21" width="7" height="1.2" fill="#5A5E68" />
          <rect x="6" y="-21" width="7" height="1.2" fill="#5A5E68" />
          <rect x="-13" y="-6.5" width="5" height="1.2" fill="#38d97a" />
          <text className="wheel__gear" x="0" y="-7.5" textAnchor="middle">{gear}</text>
          {BUTTONS.map(([x, y, c], i) => (
            <circle key={i} cx={x} cy={y} r={2.4} fill={c} stroke="#5A5E68" strokeWidth={0.6} />
          ))}
          <rect x="-29" y="-7.5" width="4" height="7" rx="2" fill="#E10600" />
          <rect x="25" y="-7.5" width="4" height="7" rx="2" fill="#4C8DFF" />
          <rect x="-22.5" y="-2" width="3" height="6" rx="0.8" fill="#FF8A1F" />
          <rect x="19.5" y="-2" width="3" height="6" rx="0.8" fill="#FF8A1F" />
          {DIALS.map(([x, c], i) => (
            <g key={i}>
              <circle cx={x} cy={17} r={3.4} fill={c} stroke="#3A3E48" strokeWidth={0.7} />
              <rect x={x - 0.5} y={13.8} width={1} height={3} fill="#0B0C0F" />
            </g>
          ))}
          <rect className="wheel__mark" x="-2.5" y="-37" width="5" height="5" />
        </g>
      </svg>
      <span ref={label} className="wheel__deg">0°</span>
    </div>
  );
}

/** Throttle and brake as two thin vertical bars. */
export function PedalBars({ store, rigId, frameHz }: { store: DashboardStore; rigId: string; frameHz: number }) {
  const thr = useRef<HTMLSpanElement>(null);
  const brk = useRef<HTMLSpanElement>(null);
  useRaf((now) => {
    const s = store.live.inputAt(rigId, now - 1000 / frameHz);
    if (thr.current) thr.current.style.transform = `scaleY(${(s?.thr ?? 0).toFixed(3)})`;
    if (brk.current) brk.current.style.transform = `scaleY(${(s?.brk ?? 0).toFixed(3)})`;
  });
  return (
    <div className="vpedals" aria-label="Throttle and brake">
      <span className="vpedal vpedal--thr"><span ref={thr} className="vpedal__fill" /></span>
      <span className="vpedal vpedal--brk"><span ref={brk} className="vpedal__fill" /></span>
    </div>
  );
}

function SpeedGear({ frame }: { frame: RigFrame | undefined }) {
  const driving = frame?.state === "driving";
  return (
    <span className="spg">
      <span className="spg__speed">{driving ? formatSpeed(frame?.speed_kph) : "–"}</span>
      <span className="spg__unit">km/h</span>
      <span className="spg__gear">{driving ? formatGear(frame?.gear) : "–"}</span>
    </span>
  );
}

function Delta({ store, rigId }: { store: DashboardStore; rigId: string }) {
  const ms = store.live.deltaToBest(rigId);
  return <span className={deltaClass(ms)}>{ms == null ? "–" : formatDelta(ms, 2)}</span>;
}

// --- MULTIVIEW -------------------------------------------------------------------------------------------

export function multiviewGrid(n: number): string {
  return n <= 1 ? "1" : n === 2 ? "2" : n <= 4 ? "4" : "6";
}

export function MultiviewPage({ store, state, trackKey }: { store: DashboardStore; state: DashboardState; trackKey: string | null }) {
  const rigs = activeRigs(state);
  return (
    <main className={`multi multi--${multiviewGrid(rigs.length)}`}>
      {rigs.map((rig) => (
        <Tile key={rig.rig_id} store={store} state={state} rig={rig} trackKey={trackKey} />
      ))}
      {rigs.length === 0 && <p className="live__empty">Each rig appears here when its car is on track.</p>}
    </main>
  );
}

function Tile({ store, state, rig, trackKey }: { store: DashboardStore; state: DashboardState; rig: RigInfo; trackKey: string | null }) {
  const frame = state.frames[rig.rig_id];
  return (
    <article className="tile" style={rigStyle(rig)} aria-label={frame?.driver ?? rig.name}>
      <header className="tile__head">
        <span className="rcard__stripe" aria-hidden="true" />
        <FitText className="tile__name" text={frame?.driver ?? rig.name} />
        <LapClock frame={frame} />
        <Delta store={store} rigId={rig.rig_id} />
      </header>
      <div className="tile__body">
        <div className="tile__drive">
          <div className="tile__spg"><SpeedGear frame={frame} /></div>
          <div className="tile__ctl">
            <SteeringWheel store={store} rigId={rig.rig_id} frameHz={state.frameHz}
                           rotationDeg={state.steeringRotationDeg} frame={frame} />
            <PedalBars store={store} rigId={rig.rig_id} frameHz={state.frameHz} />
          </div>
        </div>
        <div className="tile__map">
          <TrackMap store={store} state={state} trackKey={frame?.session.track_key ?? trackKey} displayOverride={null}
                    variant="mini" onlyRigId={rig.rig_id} />
        </div>
      </div>
    </article>
  );
}
