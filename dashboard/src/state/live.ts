import type { RigFrame } from "../schema";

// Live per-rig telemetry worked out in the dashboard from the 15 Hz frames, outside React:
//  - a short input history (pedals, steering, speed) for the 10 s pedal trace and for drawing needles at
//    display rate, interpolated between frames;
//  - the current lap and the driver's best lap as (distance, time, speed) traces, for the live delta to their
//    own best and the speed trace. Only laps this page saw from start to finish can become the best; a valid
//    lap always beats an invalid one, but until a driver has a valid lap their fastest clean lap is the
//    reference (cafe drivers cut a lot of corners).

export const PEDAL_WINDOW_MS = 10_000;
const KEEP_INPUT_MS = PEDAL_WINDOW_MS + 2_000;
const START_M = 60; // a lap must be picked up this close to the line to become a reference
const MAX_STEP_FRACTION = 0.05; // a jump of more than 5 % of the lap between frames: not a clean lap

export interface InputSample {
  t: number; // local receive time (performance.now())
  thr: number;
  brk: number;
  steer: number;
  speed: number;
}

export interface DistTrace {
  d: number[];
  t: number[];
  v: number[];
}

interface Current {
  trackKey: string;
  driver: string;
  lap: number;
  length: number;
  trace: DistTrace;
  clean: boolean;
  valid: boolean;
}

interface Best {
  trackKey: string;
  driver: string;
  lapMs: number;
  valid: boolean;
  length: number;
  trace: DistTrace;
}

/** Lap time at distance d on a trace (interpolated); null outside it. */
export function timeAt(trace: DistTrace, d: number): number | null {
  const n = trace.d.length;
  if (n < 2 || d < trace.d[0]! || d > trace.d[n - 1]!) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (trace.d[mid]! <= d) lo = mid;
    else hi = mid;
  }
  const d0 = trace.d[lo]!;
  const d1 = trace.d[hi]!;
  const k = d1 > d0 ? (d - d0) / (d1 - d0) : 0;
  return trace.t[lo]! + (trace.t[hi]! - trace.t[lo]!) * k;
}

/** Inputs at time t, interpolated between the samples either side (clamped to the newest). */
export function inputAt(samples: readonly InputSample[], t: number): InputSample | null {
  const n = samples.length;
  if (n === 0) return null;
  const last = samples[n - 1]!;
  if (t >= last.t) return last;
  if (t <= samples[0]!.t) return samples[0]!;
  for (let i = n - 1; i > 0; i--) {
    const a = samples[i - 1]!;
    if (t < a.t) continue;
    const b = samples[i]!;
    const k = b.t > a.t ? (t - a.t) / (b.t - a.t) : 1;
    const lerp = (x: number, y: number) => x + (y - x) * k;
    return { t, thr: lerp(a.thr, b.thr), brk: lerp(a.brk, b.brk), steer: lerp(a.steer, b.steer), speed: lerp(a.speed, b.speed) };
  }
  return samples[0]!;
}

export class LiveTelemetry {
  private readonly inputs = new Map<string, InputSample[]>();
  private readonly current = new Map<string, Current>();
  private readonly best = new Map<string, Best>();
  private readonly deltas = new Map<string, number | null>();

  add(frame: RigFrame, now: number): void {
    const rigId = frame.rig_id;
    if (frame.state !== "driving") {
      this.deltas.set(rigId, null);
      return;
    }
    const samples = this.inputs.get(rigId) ?? [];
    samples.push({
      t: now, thr: clamp01(frame.throttle), brk: clamp01(frame.brake),
      steer: Math.max(-1, Math.min(1, frame.car?.steer ?? 0)), speed: frame.speed_kph ?? 0,
    });
    let drop = 0;
    while (drop < samples.length && samples[drop]!.t < now - KEEP_INPUT_MS) drop++;
    if (drop) samples.splice(0, drop);
    this.inputs.set(rigId, samples);
    this.addLap(frame);
  }

  private addLap(frame: RigFrame): void {
    const rigId = frame.rig_id;
    const lap = frame.lap;
    const trackKey = frame.session.track_key;
    const length = frame.session.track_length_m;
    if (!lap || !trackKey || !length || length <= 0) return;
    const driver = frame.driver ?? rigId;
    let cur = this.current.get(rigId);
    if (cur && (cur.trackKey !== trackKey || cur.driver !== driver || lap.number < cur.lap || lap.number > cur.lap + 1)) {
      cur = undefined;
    }
    if (cur && lap.number === cur.lap + 1) {
      this.finish(rigId, cur, lap.last_ms);
      cur = undefined;
    }
    const best = this.best.get(rigId);
    if (best && (best.trackKey !== trackKey || best.driver !== driver)) this.best.delete(rigId); // new driver
    const d = lap.distance_m;
    if (!cur) {
      if (d < 0) {
        this.deltas.set(rigId, null);
        return;
      }
      cur = { trackKey, driver, lap: lap.number, length, trace: { d: [], t: [], v: [] }, clean: d <= START_M, valid: lap.valid };
      this.current.set(rigId, cur);
    }
    const tr = cur.trace;
    const lastD = tr.d[tr.d.length - 1];
    if (lastD !== undefined && (d < lastD - 1 || d - lastD > length * MAX_STEP_FRACTION)) cur.clean = false; // flashback
    if (!lap.valid) cur.valid = false;
    if (lastD === undefined || d > lastD) {
      tr.d.push(d);
      tr.t.push(lap.current_ms);
      tr.v.push(frame.speed_kph ?? 0);
    }
    const ref = this.best.get(rigId);
    const refT = ref ? timeAt(ref.trace, d) : null;
    this.deltas.set(rigId, refT == null ? null : Math.round(lap.current_ms - refT));
  }

  private finish(rigId: string, cur: Current, lapMs: number | null): void {
    const tr = cur.trace;
    const end = tr.d[tr.d.length - 1] ?? 0;
    if (!cur.clean || lapMs == null || lapMs <= 0 || end < cur.length * 0.95) return;
    // Close the trace at the line so the delta works to the very end of the next lap.
    const trace = { d: [...tr.d, cur.length], t: [...tr.t, lapMs], v: [...tr.v, tr.v[tr.v.length - 1] ?? 0] };
    const prev = this.best.get(rigId);
    const better = !prev || (cur.valid && !prev.valid) || (cur.valid === prev.valid && lapMs < prev.lapMs);
    if (better) {
      this.best.set(rigId, { trackKey: cur.trackKey, driver: cur.driver, lapMs, valid: cur.valid, length: cur.length, trace });
    }
  }

  /** Recent input samples, oldest first. */
  history(rigId: string): readonly InputSample[] {
    return this.inputs.get(rigId) ?? [];
  }

  inputAt(rigId: string, t: number): InputSample | null {
    return inputAt(this.history(rigId), t);
  }

  /** Current lap time minus the driver's best lap at the same distance; negative = ahead. */
  deltaToBest(rigId: string): number | null {
    return this.deltas.get(rigId) ?? null;
  }

  /** The current lap and the driver's best lap (by distance), for the speed trace. */
  speedTraces(rigId: string): { length: number; current: DistTrace | null; best: DistTrace | null; bestMs: number | null } | null {
    const cur = this.current.get(rigId);
    const best = this.best.get(rigId);
    const length = cur?.length ?? best?.length;
    if (!length) return null;
    return { length, current: cur?.trace ?? null, best: best?.trace ?? null, bestMs: best?.lapMs ?? null };
  }

  clear(rigId?: string): void {
    for (const map of [this.inputs, this.current, this.best, this.deltas] as Map<string, unknown>[]) {
      if (rigId === undefined) map.clear();
      else map.delete(rigId);
    }
  }
}

function clamp01(v: number | null | undefined): number {
  return Math.min(1, Math.max(0, v ?? 0));
}
