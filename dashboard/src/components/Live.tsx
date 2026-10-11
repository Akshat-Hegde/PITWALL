import { useEffect, useRef } from "react";
import { formatDelta, formatGear, formatLapTime, formatSpeed } from "../format";
import type { Display } from "../map/geometry";
import type { RigFrame, RigInfo } from "../schema";
import { PEDAL_WINDOW_MS, type DistTrace } from "../state/live";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { tyreTempBand } from "./Gauges";
import { FitText, useTvScale } from "./Stage";
import { TrackMap } from "./TrackMap";

// The two TV pages (DESIGN.md, "TV pages"): LIVE (map, one card per active rig, a trace strip for one rig)
// and MULTIVIEW (one tile per active rig). Needles (steering, pedals) and traces are drawn every animation
// frame from the dashboard's live telemetry, interpolated between the 15 Hz frames, without React renders.

const WHEELS = ["FL", "FR", "RL", "RR"] as const;
/** Traces break where samples are further apart than this (no data, menus). */
const GAP_MS = 500;
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
function useHeld<T>(value: T, holdMs: number, now: number): T {
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
    <span className={`lapclock${lap && !lap.valid ? " is-invalid" : ""}`}>
      {driving && lap ? formatLapTime(lap.current_ms) : STATE_TEXT[frame?.state ?? "no_data"] ?? "–"}
    </span>
  );
}

const STATE_TEXT: Record<string, string> = { driving: "On track", in_menu_paused: "In menu", no_data: "Waiting" };

/** Wheel body: a wide formula-style wheel with two grips, drawn by us. Screen, buttons and LED slots are
 *  cut out (even-odd), so the page shows through them. */
const WHEEL_BODY =
  "M-30 -30 L30 -30 C42 -30 47 -24 48 -14 L48 -2 C48 14 47 26 42 31 C38 35 32 33 32 27 L32 8 " +
  "C32 4 29 2 25 2 L22 2 C20 2 19 4 19 8 L19 14 C19 19 16 21 11 21 L-11 21 C-16 21 -19 19 -19 14 L-19 8 " +
  "C-19 4 -20 2 -22 2 L-25 2 C-29 2 -32 4 -32 8 L-32 27 C-32 33 -38 35 -42 31 C-47 26 -48 14 -48 -2 " +
  "L-48 -14 C-47 -24 -42 -30 -30 -30 Z " +
  // screen
  "M-12 -24 L12 -24 L12 -3 L-12 -3 Z " +
  // three buttons
  "M-12.2 11 a3.2 3.2 0 1 0 6.4 0 a3.2 3.2 0 1 0 -6.4 0 Z M-3.2 11 a3.2 3.2 0 1 0 6.4 0 a3.2 3.2 0 1 0 -6.4 0 Z " +
  "M5.8 11 a3.2 3.2 0 1 0 6.4 0 a3.2 3.2 0 1 0 -6.4 0 Z " +
  // grip slots
  "M-38 -22 L-30 -24 L-30 -20 L-38 -18 Z M38 -22 L30 -24 L30 -20 L38 -18 Z";
/** LED slots either side of the screen, bottom to top; they light up with the car's rev lights. */
const LEDS = [-7, -11, -15, -19, -23];
const LED_COLOURS = ["#38d97a", "#38d97a", "#f2c230", "#ff4a4a", "#b46cff"];

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
      const text = `${Math.round(deg)}°`;
      if (label.current.textContent !== text) label.current.textContent = text;
    }
  });
  const driving = frame?.state === "driving";
  const revs = driving ? frame?.car?.rev_lights_pct ?? null : null;
  const lit = revs == null ? 0 : Math.round((Math.max(0, Math.min(100, revs)) / 100) * LEDS.length);
  const gear = driving ? formatGear(frame?.gear) : "";
  return (
    <div className="wheel">
      <svg className="wheel__svg" viewBox="-50 -50 100 100" aria-hidden="true">
        <g ref={wheel} className="wheel__turn">
          <path className="wheel__body" d={WHEEL_BODY} fillRule="evenodd" />
          {LEDS.map((y, i) => [-21, 17].map((x) => (
            <rect key={`${x}${y}`} className="wheel__led" x={x} y={y} width="4" height="2.6" rx="0.6"
                  style={i < lit ? { fill: LED_COLOURS[i] } : undefined} />
          )))}
          <text className="wheel__gear" x="0" y="-8.5" textAnchor="middle">{gear}</text>
          <rect className="wheel__mark" x="-2.5" y="-35" width="5" height="6" />
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

/** Four tyre blocks: surface temperature as colour, pressure as the number. */
export function TyreBlocks({ frame }: { frame: RigFrame | undefined }) {
  const car = frame?.state === "driving" ? frame.car : null;
  return (
    <div className="tyres4" aria-label="Tyres">
      {WHEELS.map((w, i) => {
        const temp = car?.tyre_surface_c?.[i] ?? null;
        const psi = car?.tyre_pressure_psi?.[i] ?? null;
        return (
          <span key={w} className={`tyre4 tyre4--${tyreTempBand(temp)}`} title={`${w} ${temp ?? "–"}°C`}>
            {psi == null ? "–" : psi.toFixed(1)}
          </span>
        );
      })}
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

// --- LIVE ------------------------------------------------------------------------------------------------

interface PageProps {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  mapDisplay?: Display | null;
  /** Rig the staff pinned to the strip; null = automatic. */
  pinnedRigId?: string | null;
}

export function LivePage({ store, state, trackKey, mapDisplay = null, pinnedRigId = null }: PageProps) {
  const rigs = activeRigs(state);
  const now = performance.now();
  const stripRig = useHeld(chooseStripRig(state, store, pinnedRigId), pinnedRigId ? 0 : STRIP_HOLD_MS, now);
  const selected = rigs.find((r) => r.rig_id === stripRig) ?? null;
  return (
    <main className="live">
      <section className="live__map" aria-label="Track map">
        <TrackMap store={store} state={state} trackKey={trackKey} displayOverride={mapDisplay} />
        <MapInfo state={state} trackKey={trackKey} />
      </section>
      <section className={`live__cards live__cards--${Math.max(1, rigs.length)}`} aria-label="Rigs">
        {rigs.map((rig) => (
          <RigCard key={rig.rig_id} store={store} state={state} rig={rig} size={rigs.length > 3 ? "compact" : rigs.length > 2 ? "tall" : "large"}
                   selected={rig.rig_id === selected?.rig_id} />
        ))}
        {rigs.length === 0 && <p className="live__empty">Each rig appears here when its car is on track.</p>}
      </section>
      <TraceStrip store={store} state={state} rig={selected} pinned={pinnedRigId != null && selected != null} />
    </main>
  );
}

/** Small corner block: track, length, today's record. Nothing else in the map area. */
function MapInfo({ state, trackKey }: { state: DashboardState; trackKey: string | null }) {
  const session = Object.values(state.frames).find((f) => f.session.track_key === trackKey)?.session;
  const name = session?.track_name ?? state.leaderboards.today?.track_name ?? null;
  if (!name) return null;
  const today = state.leaderboards.today;
  const record = today && today.track_key === trackKey ? today.entries[0] ?? null : null;
  return (
    <div className="mapinfo">
      <span className="mapinfo__track">{name}</span>
      {session?.track_length_m ? <span className="mapinfo__len">{(session.track_length_m / 1000).toFixed(3)} km</span> : null}
      {record && (
        <span className="mapinfo__rec">
          <span className="label">Today</span>
          <span className="c-purple">{formatLapTime(record.lap_ms)}</span>
          <span className="t2">{record.driver ?? record.rig_name}</span>
        </span>
      )}
    </div>
  );
}

function RigCard({ store, state, rig, size, selected }: {
  store: DashboardStore; state: DashboardState; rig: RigInfo; size: "large" | "tall" | "compact"; selected: boolean;
}) {
  const frame = state.frames[rig.rig_id];
  const lap = frame?.lap;
  return (
    <article className={`rcard rcard--${size}${selected ? " is-selected" : ""}`} style={rigStyle(rig)}
             aria-label={frame?.driver ?? rig.name}>
      <header className="rcard__head">
        <span className="rcard__stripe" aria-hidden="true" />
        <FitText className="rcard__name" text={frame?.driver ?? rig.name} />
        <span className="rcard__lap">
          {lap ? `Lap ${lap.number}` : ""}
          {lap && !lap.valid && frame?.state === "driving" && <span className="invalid-tag">Invalid</span>}
        </span>
        <LapClock frame={frame} />
      </header>
      <div className="rcard__time"><LapClock frame={frame} /></div>
      <div className="rcard__delta"><Delta store={store} rigId={rig.rig_id} /></div>
      <div className="rcard__spg"><SpeedGear frame={frame} /></div>
      <SteeringWheel store={store} rigId={rig.rig_id} frameHz={state.frameHz} rotationDeg={state.steeringRotationDeg}
                     frame={frame} />
      <PedalBars store={store} rigId={rig.rig_id} frameHz={state.frameHz} />
      <TyreBlocks frame={frame} />
    </article>
  );
}

/** Bottom strip for one rig: pedals over the last 10 s, and speed this lap against the driver's best. */
function TraceStrip({ store, state, rig, pinned }: {
  store: DashboardStore; state: DashboardState; rig: RigInfo | null; pinned: boolean;
}) {
  const frame = rig ? state.frames[rig.rig_id] : undefined;
  const best = rig ? store.live.speedTraces(rig.rig_id)?.bestMs ?? null : null;
  return (
    <section className="strip" style={rig ? rigStyle(rig) : undefined} aria-label="Traces">
      <header className="strip__who">
        <span className="rcard__stripe" aria-hidden="true" />
        <FitText className="strip__name" text={rig ? frame?.driver ?? rig.name : "No car on track"} />
        <span className="label">{pinned ? "Picked by staff" : "On the fastest lap"}</span>
      </header>
      <div className="strip__panel">
        <span className="label strip__label">
          Pedals · last 10 s <span className="c-thr">Throttle</span> <span className="c-brk">Brake</span>
        </span>
        {rig && <PedalTrace store={store} rigId={rig.rig_id} frameHz={state.frameHz} />}
      </div>
      <div className="strip__panel strip__panel--wide">
        <span className="label strip__label">
          Speed · this lap vs best{best != null ? ` ${formatLapTime(best)}` : ""}
          <span className="c-ahead">Faster</span> <span className="c-behind">Slower</span>
        </span>
        {rig && <SpeedTrace store={store} rigId={rig.rig_id} colour={rig.colour} />}
      </div>
    </section>
  );
}

/** A canvas sized in layout pixels with a backing store matching the screen (sharp on a 4K TV). */
function useCanvas(draw: (ctx: CanvasRenderingContext2D, w: number, h: number, now: number) => void) {
  const ref = useRef<HTMLCanvasElement>(null);
  const scale = useTvScale();
  useRaf((now) => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const k = (window.devicePixelRatio || 1) * scale;
    if (canvas.width !== Math.round(w * k) || canvas.height !== Math.round(h * k)) {
      canvas.width = Math.round(w * k);
      canvas.height = Math.round(h * k);
    }
    ctx.setTransform(k, 0, 0, k, 0, 0);
    ctx.clearRect(0, 0, w, h);
    draw(ctx, w, h, now);
  });
  return ref;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function PedalTrace({ store, rigId, frameHz }: { store: DashboardStore; rigId: string; frameHz: number }) {
  const ref = useCanvas((ctx, w, h, now) => {
    const end = now - 1000 / frameHz;
    const samples = store.live.history(rigId);
    const x = (t: number) => w - ((end - t) / PEDAL_WINDOW_MS) * w;
    const pad = 3;
    const y = (v: number) => pad + (1 - v) * (h - 2 * pad);
    ctx.strokeStyle = cssVar("--line");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y(0) + 0.5);
    ctx.lineTo(w, y(0) + 0.5);
    ctx.stroke();
    for (const [key, colour] of [["thr", cssVar("--throttle")], ["brk", cssVar("--brake")]] as const) {
      ctx.beginPath();
      let started = false;
      let lastT = -Infinity;
      for (const s of samples) {
        if (s.t > end) break;
        const px = x(s.t);
        if (px < 0) continue;
        if (!started || s.t - lastT > GAP_MS) ctx.moveTo(px, y(s[key]));
        else ctx.lineTo(px, y(s[key]));
        started = true;
        lastT = s.t;
      }
      const head = store.live.inputAt(rigId, end);
      if (head && started && end - lastT <= GAP_MS) ctx.lineTo(w, y(head[key]));
      ctx.strokeStyle = colour;
      ctx.lineWidth = 2.5;
      ctx.lineJoin = "round";
      ctx.stroke();
    }
  });
  return <canvas ref={ref} className="strip__canvas" aria-hidden="true" />;
}

/** Speed (km/h) at distance d on a trace, interpolated; null outside it. */
export function speedAt(trace: DistTrace, d: number): number | null {
  const n = trace.d.length;
  if (n < 2 || d < trace.d[0]! || d > trace.d[n - 1]!) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (trace.d[mid]! <= d) lo = mid;
    else hi = mid;
  }
  const k = trace.d[hi]! > trace.d[lo]! ? (d - trace.d[lo]!) / (trace.d[hi]! - trace.d[lo]!) : 0;
  return trace.v[lo]! + (trace.v[hi]! - trace.v[lo]!) * k;
}

function SpeedTrace({ store, rigId, colour }: { store: DashboardStore; rigId: string; colour: string }) {
  const ref = useCanvas((ctx, w, h) => {
    const traces = store.live.speedTraces(rigId);
    if (!traces) return;
    const { length, current, best } = traces;
    const pad = 3;
    const gap = length * 0.02; // missing data (the page joined late, the feed dropped): leave a gap
    const top = Math.max(320, ...(best?.v ?? [0]), ...(current?.v ?? [0]));
    const x = (d: number) => (d / length) * w;
    const y = (v: number) => pad + (1 - v / top) * (h - 2 * pad);
    // Gap between this lap and the best, shaded green where faster and red where slower.
    if (current && best && current.d.length > 1) {
      const ahead = cssVar("--delta-ahead");
      const behind = cssVar("--delta-behind");
      ctx.globalAlpha = 0.28;
      for (let i = 1; i < current.d.length; i++) {
        const d0 = current.d[i - 1]!;
        const d1 = current.d[i]!;
        const b0 = speedAt(best, d0);
        const b1 = speedAt(best, d1);
        if (b0 == null || b1 == null || d1 - d0 > gap) continue;
        const v0 = current.v[i - 1]!;
        const v1 = current.v[i]!;
        ctx.fillStyle = v0 + v1 >= b0 + b1 ? ahead : behind;
        ctx.beginPath();
        ctx.moveTo(x(d0), y(v0));
        ctx.lineTo(x(d1), y(v1));
        ctx.lineTo(x(d1), y(b1));
        ctx.lineTo(x(d0), y(b0));
        ctx.closePath();
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
    const line = (trace: DistTrace, stroke: string, width: number) => {
      ctx.beginPath();
      trace.d.forEach((d, i) => (i === 0 || d - trace.d[i - 1]! > gap
        ? ctx.moveTo(x(d), y(trace.v[i]!)) : ctx.lineTo(x(d), y(trace.v[i]!))));
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.lineJoin = "round";
      ctx.stroke();
    };
    if (best) line(best, cssVar("--text-3"), 1.5);
    if (current) line(current, colour, 2.5);
  });
  return <canvas ref={ref} className="strip__canvas" aria-hidden="true" />;
}

// --- MULTIVIEW -------------------------------------------------------------------------------------------

export function multiviewGrid(n: number): string {
  return n <= 1 ? "1" : n === 2 ? "2" : n <= 4 ? "4" : "6";
}

export function MultiviewPage({ store, state, trackKey }: PageProps) {
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
