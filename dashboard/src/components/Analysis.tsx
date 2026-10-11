import { formatDelta, formatLapTime } from "../format";
import {
  IDENTITY_DISPLAY,
  emptyBounds,
  extend,
  fitBounds,
  isEmpty,
  project,
  toMapPlane,
  type Display,
} from "../map/geometry";
import type { HeadToHeadSide, RigFrame, RigInfo, TrackOutline } from "../schema";
import {
  MINI_SECTORS,
  fasterPerMini,
  speedZones,
  type LapTrace,
  type LapTraceTracker,
  type SpeedZone,
} from "../state/laptrace";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { Avatar, StripeBundle, Tab } from "./Motifs";
import { away } from "./TrackMap";
import { runningOrder } from "./Timing";

export interface DuelSide {
  rig: RigInfo;
  frame: RigFrame | undefined;
  name: string;
  trace: LapTrace;
  position: number | null;
}

export interface Duel {
  a: DuelSide; // the faster of the two
  b: DuelSide;
  who: ("a" | "b")[];
  zones: SpeedZone[];
}

function hubSide(state: DashboardState, s: HeadToHeadSide, trackKey: string, position: number | null): DuelSide {
  const rig = state.rigs.find((r) => r.rig_id === s.rig_id)
    ?? { rig_id: s.rig_id, name: "Rig", colour: "#8a8f99", address: "", game: "F1", data_format: null, format_supported: true };
  const trace: LapTrace = {
    rigId: s.rig_id, trackKey, lapNumber: s.lap_number, lapMs: s.lap_ms, valid: true, minis: s.minis, speed: s.speed,
    share: { fullThrottle: s.share.full_throttle ?? 0, heavyBraking: s.share.heavy_braking ?? 0,
             cornering: s.share.cornering ?? 0 },
  };
  return { rig, frame: state.frames[s.rig_id], name: s.driver ?? rig.name, trace, position };
}

/**
 * The two drivers to compare. From the hub when it has them (kept per track and day, so a TV reload shows
 * them at once); otherwise the closest pair by the best laps this page has a full trace of (mock data).
 */
/** Two rig colours too alike to tell apart on the map: B gets a contrasting colour instead (blue or orange). */
export function distinctColours(a: string, b: string): [string, string] {
  const rgb = (c: string) => {
    const m = /^#([0-9a-f]{6})$/i.exec(c);
    const n = m ? parseInt(m[1]!, 16) : 0x888888;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const [x, y] = [rgb(a), rgb(b)];
  const distance = Math.hypot(x[0]! - y[0]!, x[1]! - y[1]!, x[2]! - y[2]!);
  if (distance >= 110) return [a, b];
  const blue = "#3987e5";
  const orange = "#d95926";
  return [a, Math.hypot(...rgb(a).map((v, i) => v - rgb(blue)[i]!)) > 140 ? blue : orange];
}

function withColours(duel: Duel): Duel {
  const [, cb] = distinctColours(duel.a.rig.colour, duel.b.rig.colour);
  return cb === duel.b.rig.colour ? duel : { ...duel, b: { ...duel.b, rig: { ...duel.b.rig, colour: cb } } };
}

export function chooseDuel(state: DashboardState, laps: LapTraceTracker, trackKey: string | null): Duel | null {
  const duel = pickDuel(state, laps, trackKey);
  return duel ? withColours(duel) : null;
}

function pickDuel(state: DashboardState, laps: LapTraceTracker, trackKey: string | null): Duel | null {
  if (!trackKey) return null;
  const h = state.headToHead;
  if (h && h.track_key === trackKey) {
    const positions = new Map((state.leaderboards.today?.entries ?? []).map((e) => [e.driver, e.rank]));
    const a = hubSide(state, h.a, trackKey, positions.get(h.a.driver) ?? 1);
    const b = hubSide(state, h.b, trackKey, positions.get(h.b.driver) ?? 2);
    return { a, b, who: fasterPerMini(a.trace, b.trace), zones: speedZones(a.trace.speed) };
  }
  const positions = new Map(runningOrder(state, trackKey).map((o) => [o.rig.rig_id, o.position]));
  const sides: DuelSide[] = state.rigs
    .map((rig) => ({ rig, trace: laps.bestLap(rig.rig_id, trackKey) }))
    .filter((x): x is { rig: RigInfo; trace: LapTrace } => x.trace !== null)
    .map(({ rig, trace }) => {
      const frame = state.frames[rig.rig_id];
      return { rig, frame, trace, name: frame?.driver ?? rig.name, position: positions.get(rig.rig_id) ?? null };
    })
    .sort((x, y) => x.trace.lapMs - y.trace.lapMs);
  if (sides.length < 2) return null;
  let pair: [DuelSide, DuelSide] = [sides[0]!, sides[1]!];
  for (let i = 1; i < sides.length - 1; i++) {
    if (sides[i + 1]!.trace.lapMs - sides[i]!.trace.lapMs < pair[1].trace.lapMs - pair[0].trace.lapMs) {
      pair = [sides[i]!, sides[i + 1]!];
    }
  }
  const [a, b] = pair;
  return { a, b, who: fasterPerMini(a.trace, b.trace), zones: speedZones(a.trace.speed) };
}

const ZONE_TEXT = { low: "Low", medium: "Medium", high: "High" } as const;

export function AnalysisView({ store, state, trackKey }: { store: DashboardStore; state: DashboardState;
                                                           trackKey: string | null }) {
  const duel = chooseDuel(state, store.laps, trackKey);
  const outline = trackKey ? state.outlines[trackKey] : undefined;
  const trackName = outline?.track_name ?? state.leaderboards.today?.track_name ?? null;
  return (
    <main className="analysis">
      <StripeBundle corner="top-right" className="analysis__stripes" />
      <header className="viewhead">
        <h1 className="viewhead__title">Head to head</h1>
        {duel && (
          <span className="viewhead__sub">
            {duel.a.name} v {duel.b.name}
            {trackName && <span className="t3"> · {trackName}</span>}
            <span className="t3"> · best laps</span>
          </span>
        )}
      </header>
      {!duel ? (
        <p className="analysis__empty">
          The head to head appears once two drivers have each driven a full lap on {trackName ?? "the track"} with
          this screen on.
        </p>
      ) : (
        <>
          <div className="analysis__top">
            <Side duel={duel} side="a" />
            <div className="analysis__map">
              {outline ? <DuelMap duel={duel} outline={outline} /> : <p className="t3">Track outline after a clean lap</p>}
              <div className="analysis__legend">
                {(["a", "b"] as const).map((k) => (
                  <span key={k} style={{ "--rig-colour": duel[k].rig.colour } as React.CSSProperties}>
                    <span className="legend-line" aria-hidden="true" />
                    {duel[k].name} faster
                  </span>
                ))}
              </div>
            </div>
            <Side duel={duel} side="b" />
          </div>
          <SpeedTrace duel={duel} />
        </>
      )}
    </main>
  );
}

const SHARE_ROWS = [
  ["fullThrottle", "Full throttle"],
  ["heavyBraking", "Heavy braking"],
  ["cornering", "Cornering"],
] as const;

function Side({ duel, side }: { duel: Duel; side: "a" | "b" }) {
  const me = duel[side];
  const other = duel[side === "a" ? "b" : "a"];
  const gap = me.trace.lapMs - other.trace.lapMs;
  const won = duel.who.filter((w) => w === side).length;
  return (
    <section className={`duel duel--${side}`} style={{ "--rig-colour": me.rig.colour } as React.CSSProperties}
             aria-label={me.name}>
      <div className="duel__id">
        <Avatar name={me.name} className="avatar--l" />
        <div className="field">
          <span className="label">Position</span>
          <span className="duel__pos">{me.position ?? "–"}</span>
        </div>
        <div className="field duel__driver">
          <span className="label">Driver</span>
          <span className="duel__who">
            <span className="stripe" aria-hidden="true" />
            <span>
              <span className="duel__name">{me.name}</span>
              <span className="duel__rig">{me.rig.name} · lap {me.trace.lapNumber}</span>
            </span>
          </span>
        </div>
      </div>
      <div className="duel__times">
        <div className="field">
          <span className="label">Lap time</span>
          <span className="duel__value">{formatLapTime(me.trace.lapMs)}</span>
        </div>
        <div className="field">
          <span className="label">Gap</span>
          <span className="duel__value">{formatDelta(gap)}</span>
        </div>
        <div className="field">
          <span className="label">Mini-sectors</span>
          <span className="duel__value">
            {won}
            <span className="unit">/ {MINI_SECTORS}</span>
          </span>
        </div>
      </div>
      <div className="duel__share">
        <Tab left="% of lap time" />
        {SHARE_ROWS.map(([key, label]) => {
          const v = me.trace.share[key];
          return (
            <div key={key} className="duel__row">
              <span className="duel__row-label">{label}</span>
              <span className="duel__bar"><span style={{ width: `${Math.min(100, v)}%` }} /></span>
              <span className="duel__pct">{Math.round(v)}<span className="unit">%</span></span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---- Map: who's faster per mini-sector, speed zones ---------------------------------------------

const VB_W = 1000;
const VB_H = 720;

function DuelMap({ duel, outline }: { duel: Duel; outline: TrackOutline }) {
  const display: Display = outline.display ?? IDENTITY_DISPLAY;
  const bounds = emptyBounds();
  for (const [x, z] of outline.points) {
    const [px, py] = toMapPlane(x, z, display);
    extend(bounds, px, py);
  }
  if (isEmpty(bounds)) return null;
  const fit = fitBounds(bounds, VB_W, VB_H, 120);
  const pts = outline.points.map(([x, z]) => {
    const [px, py] = toMapPlane(x, z, display);
    return project(fit, px, py);
  });
  const n = pts.length;
  const centre: [number, number] = [pts.reduce((s, p) => s + p[0], 0) / n, pts.reduce((s, p) => s + p[1], 0) / n];
  const path = (from: number, to: number) =>
    Array.from({ length: to - from + 1 }, (_, k) => pts[(from + k) % n]!)
      .map(([x, y], k) => `${k === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
      .join(" ");
  const at = (frac: number) => pts[Math.floor(frac * n) % n]!;

  // Zone labels off the track, pushed out until they don't overlap.
  const placed: { x: number; y: number }[] = [];
  const labels = duel.zones.map((z) => {
    const [x, y] = at(z.at);
    const [dx, dy] = away(centre, x, y);
    let d = 70;
    let lx = x + dx * d;
    let ly = y + dy * d;
    for (let i = 0; i < 6 && placed.some((p) => Math.abs(p.x - lx) < 95 && Math.abs(p.y - ly) < 46); i++) {
      d += 40;
      lx = x + dx * d;
      ly = y + dy * d;
    }
    lx = Math.max(50, Math.min(VB_W - 50, lx));
    ly = Math.max(24, Math.min(VB_H - 24, ly));
    placed.push({ x: lx, y: ly });
    return { z, x, y, lx, ly, dy };
  });

  const [s0x, s0y] = pts[0]!;
  const [s1x, s1y] = pts[1 % n]!;
  const len = Math.hypot(s1x - s0x, s1y - s0y) || 1;
  const nx = -(s1y - s0y) / len;
  const ny = (s1x - s0x) / len;
  return (
    <svg className="duelmap" viewBox={`0 0 ${VB_W} ${VB_H}`} role="img"
         aria-label={`Track coloured by the faster driver per mini-sector: ${duel.a.name} or ${duel.b.name}`}>
      <path d={path(0, n)} className="duelmap__base" />
      {duel.who.map((w, k) => (
        <path key={k} d={path(Math.floor((k / MINI_SECTORS) * n), Math.floor(((k + 1) / MINI_SECTORS) * n))}
              className="duelmap__mini" style={{ stroke: duel[w].rig.colour }} />
      ))}
      <line x1={s0x - nx * 16} y1={s0y - ny * 16} x2={s0x + nx * 16} y2={s0y + ny * 16} className="duelmap__start" />
      {labels.map(({ z, x, y, lx, ly, dy }, i) => (
        <g key={i} className="duelmap__zone">
          <line x1={x} y1={y} x2={lx} y2={ly + (dy < 0 ? 14 : -14)} />
          <circle cx={x} cy={y} r="4" />
          <text x={lx} y={ly - 2}>{ZONE_TEXT[z.kind]}</text>
          <text x={lx} y={ly + 14}>Speed</text>
        </g>
      ))}
    </svg>
  );
}

// ---- Speed traces --------------------------------------------------------------------------------

function SpeedTrace({ duel }: { duel: Duel }) {
  const a = duel.a.trace.speed;
  const b = duel.b.trace.speed;
  const all = [...a, ...b].filter((v): v is number => v != null);
  const top = Math.ceil((Math.max(...all) + 10) / 50) * 50;
  const bottom = Math.max(0, Math.floor((Math.min(...all) - 20) / 50) * 50);
  const y = (v: number) => 100 - ((v - bottom) / (top - bottom)) * 100;
  const line = (s: (number | null)[]) =>
    s.map((v, i) => (v == null ? null : `${((i + 0.5) / s.length) * 1000},${y(v).toFixed(2)}`))
      .filter(Boolean)
      .join(" ");
  const grid = [];
  for (let v = bottom + 50; v < top; v += 50) grid.push(v);
  return (
    <section className="trace" aria-label="Speed traces">
      <div className="trace__axis">
        <span className="label">Speed km/h</span>
        {grid.map((v) => (
          <span key={v} className="trace__tick" style={{ top: `${y(v)}%` }}>{v}</span>
        ))}
      </div>
      <div className="trace__plot">
        <div className="trace__zones">
          {duel.zones.map((z, i) => (
            <span key={i} className="trace__zone" style={{ left: `${z.at * 100}%` }}>
              <span className="label">{ZONE_TEXT[z.kind]} speed</span>
            </span>
          ))}
        </div>
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" className="trace__svg" aria-hidden="true">
          {grid.map((v) => <line key={v} x1="0" x2="1000" y1={y(v)} y2={y(v)} className="trace__grid" />)}
          <polyline points={line(b)} style={{ stroke: duel.b.rig.colour }} className="trace__line" />
          <polyline points={line(a)} style={{ stroke: duel.a.rig.colour }} className="trace__line" />
        </svg>
        <div className="trace__minis">
          {duel.who.map((w, k) => (
            <span key={k} className="trace__mini" style={{ "--rig-colour": duel[w].rig.colour } as React.CSSProperties}>
              <span className="trace__mini-line" aria-hidden="true" />
              <span className="trace__delta">
                {formatDelta(duel.a.trace.minis[k]! - duel.b.trace.minis[k]!)}
              </span>
            </span>
          ))}
        </div>
      </div>
      <div className="trace__foot">
        <span className="label">Delta per mini-sector, {duel.a.name} to {duel.b.name}</span>
      </div>
    </section>
  );
}
