import { useEffect, useRef } from "react";
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

/** A modern formula steering wheel as a technical line drawing (our own drawing): dark body, fine light
 *  outlines, LED rings, a bezel screen with the gear, button rows, shoulder rotaries, ribbed thumbwheels and
 *  three pointer rotaries. Monochrome except the lit rev LEDs, the gear and the rig marker. */
const WHEEL_OUTLINE =
  "M-50 -30 C-20 -37 20 -37 50 -30 C57 -28 60 -18 58 -6 C57 10 55 30 47 40 C43 44 36 42 36 35 " +
  "C37 22 36 12 31 8 C31 18 30 26 22 30 L-22 30 C-30 26 -31 18 -31 8 C-36 12 -37 22 -36 35 " +
  "C-36 42 -43 44 -47 40 C-55 30 -57 10 -58 -6 C-60 -18 -57 -28 -50 -30 Z";
/** Grip contours (the rubber grip) and the centre plate's edge. */
const WHEEL_LINES = [
  "M-53 -12 C-53 6 -51 24 -45 36",
  "M53 -12 C53 6 51 24 45 36",
  "M-31 -26 C-33 -10 -33 0 -31 8",
  "M31 -26 C33 -10 33 0 31 8",
];
const LED_X = Array.from({ length: 14 }, (_, i) => -15.6 + i * 2.4);
/** Rev LEDs light from both ends inwards: green, red, then blue-purple at the limit. */
const LED_ORDER = [0, 13, 1, 12, 2, 11, 3, 10, 4, 9, 5, 8, 6, 7];
const LED_COLOUR = (rank: number) => (rank < 5 ? "#38d97a" : rank < 10 ? "#ff3b30" : "#8f7bff");
const BUTTONS: [number, number, number][] = [
  [-25, -17, 2.9], [-25, -8, 2.7], [-25, 1, 2.7], [-24, 10, 2.7], [-38, 10, 2.4],
  [25, -17, 2.9], [25, -8, 2.7], [25, 1, 2.7], [24, 10, 2.7], [38, 10, 2.4],
];
const SHOULDERS: [number, number][] = [[-42, -21], [42, -21]];
const THUMBWHEELS: [number, number][] = [[-37, -7], [35, -7]];
const ROTARIES: [number, number, number, number][] = [[-12, 19, 4.6, -35], [0, 20, 5.6, 0], [12, 19, 4.6, 35]];
const INK = "#E6E8EC";
const INK_2 = "#8A8F9C";
const BODY = "#16181E";

/** A formula steering wheel that turns with the driver's input: rev LEDs, the gear on its screen, and the
 *  angle in degrees under it. */
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
  return (
    <div className="wheel">
      <svg className="wheel__svg" viewBox="-62 -62 124 124" aria-hidden="true">
        <g ref={wheel} className="wheel__turn" fill="none" stroke={INK} strokeLinecap="round" strokeLinejoin="round">
          <path d={WHEEL_OUTLINE} fill={BODY} strokeWidth={1.6} />
          {WHEEL_LINES.map((d, i) => <path key={i} d={d} stroke={INK_2} strokeWidth={0.9} />)}
          {/* LED rings */}
          <rect x="-18" y="-32" width="36" height="5" rx="2.5" stroke={INK_2} strokeWidth={0.8} />
          {LED_X.map((x, i) => {
            const rank = LED_ORDER.indexOf(i);
            return <circle key={i} cx={x} cy={-29.5} r={0.95} strokeWidth={0.5} stroke={INK_2}
                           fill={rank < lit ? LED_COLOUR(rank) : "none"} />;
          })}
          {/* bezel and screen */}
          <rect x="-19.5" y="-25.5" width="39" height="25" rx="3" stroke={INK_2} strokeWidth={0.9} />
          <rect x="-17" y="-23" width="34" height="20" rx="1.6" fill="#0B0C0F" strokeWidth={1.1} />
          <text className="wheel__gear" x="0" y="-8" textAnchor="middle" stroke="none">{gear}</text>
          <line x1="-14.5" y1="-20.5" x2="-8.5" y2="-20.5" stroke={INK_2} strokeWidth={0.8} />
          <line x1="8.5" y1="-20.5" x2="14.5" y2="-20.5" stroke={INK_2} strokeWidth={0.8} />
          {/* buttons: ring + inner disc */}
          {BUTTONS.map(([x, y, r], i) => (
            <g key={i}>
              <circle cx={x} cy={y} r={r} fill={BODY} strokeWidth={0.9} />
              <circle cx={x} cy={y} r={r * 0.55} stroke={INK_2} strokeWidth={0.6} />
            </g>
          ))}
          {/* shoulder rotaries with a pointer */}
          {SHOULDERS.map(([x, y], i) => (
            <g key={i}>
              <circle cx={x} cy={y} r={4.4} fill={BODY} strokeWidth={1} />
              <circle cx={x} cy={y} r={2.6} stroke={INK_2} strokeWidth={0.6} />
              <line x1={x} y1={y} x2={x} y2={y - 3.6} strokeWidth={1} />
            </g>
          ))}
          {/* ribbed thumbwheels */}
          {THUMBWHEELS.map(([x, y], i) => (
            <g key={i}>
              <rect x={x} y={y} width={3.4} height={11} rx={1.2} fill={BODY} strokeWidth={0.9} />
              {[2, 4, 6, 8].map((k) => <line key={k} x1={x + 0.6} x2={x + 2.8} y1={y + 1.5 + k} y2={y + 1.5 + k} stroke={INK_2} strokeWidth={0.5} />)}
            </g>
          ))}
          {/* pointer rotaries; the middle one with a tick ring */}
          {ROTARIES.map(([x, y, r, a], i) => (
            <g key={i}>
              {i === 1 && Array.from({ length: 12 }, (_, k) => {
                const t = ((k / 12) * 300 - 150) * (Math.PI / 180);
                return <circle key={k} cx={x + Math.sin(t) * (r + 2.6)} cy={y - Math.cos(t) * (r + 2.6)} r={0.45} fill={INK_2} stroke="none" />;
              })}
              <circle cx={x} cy={y} r={r} fill={BODY} strokeWidth={1} />
              <path d={`M${x - 1.3} ${y + r * 0.55} L${x} ${y - r * 0.95} L${x + 1.3} ${y + r * 0.55} Z`}
                    transform={`rotate(${a} ${x} ${y})`} fill="#2A2D35" strokeWidth={0.8} />
            </g>
          ))}
          <rect className="wheel__mark" x="-2.5" y="-40" width="5" height="4" stroke="none" />
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
