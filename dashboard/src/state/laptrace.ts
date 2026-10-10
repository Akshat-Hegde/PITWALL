import type { RigFrame } from "../schema";
import { CORNERING_G, FULL_THROTTLE, HEAVY_BRAKING, type LapShare } from "./lapshare";

// Mini-sectors and speed traces worked out in the dashboard from the 15 Hz frames (lap distance, lap time,
// speed). The hub doesn't send per-distance data; this is enough for broadcast-style mini-sector colours
// and the head-to-head view. Only laps this page saw from start to finish count.

export const MINI_SECTORS = 24; // 8 per sector (by distance, not by the game's sector lines)
export const SPEED_BINS = 200; // speed trace resolution: one value per 0.5 % of the lap
const MAX_STEP_FRACTION = 0.05; // a jump of more than 5 % of the lap between frames: not a clean lap
const START_FRACTION = 1 / MINI_SECTORS; // a lap must be picked up within the first mini-sector

export type MiniRating = "purple" | "green" | "yellow" | "invalid";

export interface LapTrace {
  rigId: string;
  trackKey: string;
  lapNumber: number;
  lapMs: number;
  valid: boolean;
  /** Time in each mini-sector (ms). */
  minis: number[];
  /** Mean speed (km/h) in each of SPEED_BINS distance bins; null where no sample landed. */
  speed: (number | null)[];
  share: LapShare;
}

interface Progress {
  trackKey: string;
  trackLength: number;
  lap: number;
  lastD: number;
  lastT: number;
  /** Lap time (ms) at each mini-sector boundary crossed; index 0 is the line (0 ms). */
  crossings: number[];
  clean: boolean;
  valid: boolean;
  speedSum: number[];
  speedN: number[];
  n: number;
  thr: number;
  brk: number;
  cor: number;
}

export interface LiveMinis {
  trackKey: string;
  lap: number;
  /** One entry per completed mini-sector of the current lap, in order. */
  ratings: MiniRating[];
}

export class LapTraceTracker {
  private readonly progress = new Map<string, Progress>();
  private readonly best = new Map<string, LapTrace>(); // rig -> fastest clean valid lap (on its track)
  private readonly last = new Map<string, LapTrace>();
  private readonly rigBestMinis = new Map<string, number[]>(); // `${rig}|${track}` -> best per mini
  private readonly trackBestMinis = new Map<string, number[]>(); // track -> fastest per mini, any rig
  private readonly live = new Map<string, LiveMinis>();
  /** Bumped when a lap completes: lets views memoise on it. */
  version = 0;

  add(frame: RigFrame): void {
    const lap = frame.lap;
    const trackKey = frame.session.track_key;
    const length = frame.session.track_length_m;
    if (frame.state !== "driving" || !lap || !trackKey || !length || length <= 0) return;
    const d = lap.distance_m;
    const t = lap.current_ms;
    let p = this.progress.get(frame.rig_id);

    if (p && (p.trackKey !== trackKey || lap.number < p.lap || lap.number > p.lap + 1)) p = undefined;
    if (p && lap.number === p.lap + 1) {
      this.finish(frame.rig_id, p, lap.last_ms);
      p = undefined;
    }
    if (!p) {
      if (d < 0) return; // before the line: wait for the lap to start
      p = {
        trackKey, trackLength: length, lap: lap.number, lastD: d, lastT: t, crossings: [0],
        clean: d <= length * START_FRACTION, valid: lap.valid,
        speedSum: new Array(SPEED_BINS).fill(0), speedN: new Array(SPEED_BINS).fill(0),
        n: 0, thr: 0, brk: 0, cor: 0,
      };
      this.progress.set(frame.rig_id, p);
      this.live.set(frame.rig_id, { trackKey, lap: lap.number, ratings: [] });
    }

    if (d < p.lastD || t < p.lastT || d - p.lastD > length * MAX_STEP_FRACTION) p.clean = false; // flashback, teleport
    if (!lap.valid) p.valid = false;
    // Mini-sector boundaries crossed since the last frame, interpolated in time.
    const step = length / MINI_SECTORS;
    while (p.crossings.length < MINI_SECTORS) {
      const boundary = p.crossings.length * step;
      if (d < boundary) break;
      const span = d - p.lastD;
      const at = span > 0 && boundary > p.lastD ? p.lastT + ((boundary - p.lastD) / span) * (t - p.lastT) : t;
      p.crossings.push(at);
      this.rateLive(frame.rig_id, p);
    }
    const bin = Math.min(SPEED_BINS - 1, Math.max(0, Math.floor((d / length) * SPEED_BINS)));
    if (frame.speed_kph != null) {
      p.speedSum[bin]! += frame.speed_kph;
      p.speedN[bin]! += 1;
    }
    p.n += 1;
    if ((frame.throttle ?? 0) >= FULL_THROTTLE) p.thr += 1;
    if ((frame.brake ?? 0) >= HEAVY_BRAKING) p.brk += 1;
    if (Math.abs(frame.car?.g_lat ?? 0) >= CORNERING_G) p.cor += 1;
    p.lastD = d;
    p.lastT = t;
  }

  private rateLive(rigId: string, p: Progress): void {
    const live = this.live.get(rigId);
    if (!live) return;
    const k = p.crossings.length - 1; // the mini-sector just completed
    const ms = p.crossings[k]! - p.crossings[k - 1]!;
    live.ratings.push(rateMini(ms, p.valid && p.clean, this.trackBestMinis.get(p.trackKey)?.[k - 1],
      this.rigBestMinis.get(`${rigId}|${p.trackKey}`)?.[k - 1]));
  }

  private finish(rigId: string, p: Progress, lapMs: number | null): void {
    if (!p.clean || lapMs == null || p.crossings.length < MINI_SECTORS || p.n < MINI_SECTORS) return;
    const minis = p.crossings.map((c, i) => (i + 1 < p.crossings.length ? p.crossings[i + 1]! : lapMs) - c);
    if (minis.some((m) => m <= 0)) return;
    const trace: LapTrace = {
      rigId, trackKey: p.trackKey, lapNumber: p.lap, lapMs, valid: p.valid, minis,
      speed: p.speedSum.map((s, i) => (p.speedN[i] ? s / p.speedN[i]! : null)),
      share: { fullThrottle: (p.thr / p.n) * 100, heavyBraking: (p.brk / p.n) * 100, cornering: (p.cor / p.n) * 100 },
    };
    this.last.set(rigId, trace);
    if (trace.valid) {
      const prev = this.best.get(rigId);
      if (!prev || prev.trackKey !== trace.trackKey || trace.lapMs < prev.lapMs) this.best.set(rigId, trace);
      mergeBest(this.rigBestMinis, `${rigId}|${p.trackKey}`, minis);
      mergeBest(this.trackBestMinis, p.trackKey, minis);
    }
    this.version += 1;
  }

  /** Mini-sector colours of the rig's current lap so far. */
  liveMinis(rigId: string): LiveMinis | null {
    return this.live.get(rigId) ?? null;
  }

  bestLap(rigId: string, trackKey: string): LapTrace | null {
    const t = this.best.get(rigId);
    return t && t.trackKey === trackKey ? t : null;
  }

  lastLap(rigId: string, trackKey: string): LapTrace | null {
    const t = this.last.get(rigId);
    return t && t.trackKey === trackKey ? t : null;
  }

  clear(rigId?: string): void {
    if (rigId === undefined) {
      this.progress.clear();
      this.best.clear();
      this.last.clear();
      this.rigBestMinis.clear();
      this.trackBestMinis.clear();
      this.live.clear();
    } else {
      this.progress.delete(rigId);
      this.live.delete(rigId);
    }
    this.version += 1;
  }
}

function mergeBest(map: Map<string, number[]>, key: string, minis: number[]): void {
  const cur = map.get(key);
  map.set(key, cur ? cur.map((m, i) => Math.min(m, minis[i]!)) : minis.slice());
}

/** Purple: at least as fast as anyone so far; green: own best; yellow: slower. */
export function rateMini(ms: number, valid: boolean, trackBest: number | undefined, ownBest: number | undefined): MiniRating {
  if (!valid) return "invalid";
  if (trackBest === undefined || ms <= trackBest) return "purple";
  if (ownBest === undefined || ms <= ownBest) return "green";
  return "yellow";
}

/** Per mini-sector: which driver was faster (a or b), comparing two lap traces. */
export function fasterPerMini(a: LapTrace, b: LapTrace): ("a" | "b")[] {
  return a.minis.map((m, i) => (m <= b.minis[i]! ? "a" : "b"));
}

export type SpeedClass = "low" | "medium" | "high";

export interface SpeedZone {
  /** Fraction of the lap (0..1) at the slowest point of the corner. */
  at: number;
  minKph: number;
  kind: SpeedClass;
}

const ZONE_WINDOW = 8; // bins either side (4 % of the lap)
const ZONE_MIN_DROP_KPH = 30;

/** Corners from a speed trace: local speed minima, classed by their minimum speed. */
export function speedZones(speed: (number | null)[], maxZones = 9): SpeedZone[] {
  const n = speed.length;
  const v = fillGaps(speed);
  if (!v) return [];
  const zones: SpeedZone[] = [];
  for (let i = 0; i < n; i++) {
    let isMin = true;
    let peak = -Infinity;
    for (let k = -ZONE_WINDOW; k <= ZONE_WINDOW && isMin; k++) {
      if (k === 0) continue;
      const w = v[(i + k + n) % n]!;
      if (w < v[i]! || (w === v[i]! && k < 0)) isMin = false;
      peak = Math.max(peak, w);
    }
    if (!isMin || peak - v[i]! < ZONE_MIN_DROP_KPH) continue;
    const minKph = v[i]!;
    zones.push({ at: (i + 0.5) / n, minKph, kind: minKph < 125 ? "low" : minKph < 200 ? "medium" : "high" });
  }
  // Keep the most pronounced corners if there are many.
  return zones.sort((a, b) => a.minKph - b.minKph).slice(0, maxZones).sort((a, b) => a.at - b.at);
}

function fillGaps(speed: (number | null)[]): number[] | null {
  const known = speed.filter((s): s is number => s != null);
  if (known.length < speed.length / 2) return null;
  const out = speed.slice() as (number | null)[];
  const n = out.length;
  for (let i = 0; i < n; i++) {
    if (out[i] != null) continue;
    let k = 1;
    while (k < n && speed[(i - k + n) % n] == null && speed[(i + k) % n] == null) k++;
    out[i] = speed[(i - k + n) % n] ?? speed[(i + k) % n] ?? known[0]!;
  }
  return out as number[];
}
