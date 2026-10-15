import { useEffect, useRef } from "react";
import wheelArt from "../assets/wheel.webp";
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

/** The steering wheel artwork supplied by the cafe owner (background removed; cropped to the wheel, 1057 x 620 source
 *  pixels). The rev LEDs and the gear are drawn live on top of it. */
const WHEEL_W = 116;
const WHEEL_K = WHEEL_W / 1057;                                   // source pixel -> viewBox unit
const WHEEL_H = 620 * WHEEL_K;
const src = (x: number, y: number): [number, number] => [(x - 26) * WHEEL_K - WHEEL_W / 2, (y - 83) * WHEEL_K - WHEEL_H / 2];
/** Rev LED centres in the artwork (green, red, blue; they light left to right). */
const LEDS = [385, 409, 432.5, 456, 480.5, 503.5, 527, 552.5, 575.5, 599, 622.5, 646, 670, 693.5, 717.5].map((x) => src(x, 162));
const LED_R = 7 * WHEEL_K;
const [SCREEN_X, SCREEN_Y] = src(552, 312);

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
  const lit = revs == null ? 0 : Math.round((Math.max(0, Math.min(100, revs)) / 100) * LEDS.length);
  const gear = driving ? formatGear(frame?.gear) : "";
  return (
    <div className="wheel">
      <svg className="wheel__svg" viewBox="-67 -67 134 134" aria-hidden="true">
        <g ref={wheel} className="wheel__turn">
          <image href={wheelArt} x={-WHEEL_W / 2} y={-WHEEL_H / 2} width={WHEEL_W} height={WHEEL_H} />
          {LEDS.map(([x, y], i) => i >= lit && <circle key={i} cx={x} cy={y} r={LED_R} fill="#17171a" />)}
          <text className="wheel__gear" x={SCREEN_X} y={SCREEN_Y + 5.5} textAnchor="middle" stroke="none">{gear}</text>
          <rect className="wheel__mark" x="-2.5" y={-WHEEL_H / 2 - 6} width="5" height="4" />
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

/** MULTIVIEW shows at most this many tiles (a 4 x 3 grid). */
export const MULTIVIEW_MAX = 12;

/** Grid for n tiles: 1, 2 side by side, 2 x 2, 3 x 2, 4 x 2 or 4 x 3 (the CSS class multi--<cells>). */
export function multiviewGrid(n: number): string {
  return n <= 1 ? "1" : n === 2 ? "2" : n <= 4 ? "4" : n <= 6 ? "6" : n <= 8 ? "8" : "12";
}

export function MultiviewPage({ store, state, trackKey }: { store: DashboardStore; state: DashboardState; trackKey: string | null }) {
  const rigs = activeRigs(state).slice(0, MULTIVIEW_MAX);
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
