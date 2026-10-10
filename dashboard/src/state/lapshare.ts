import type { RigFrame } from "../schema";

// Share of the lap spent at full throttle, under heavy braking and cornering hard, from the frames the
// dashboard receives (15 Hz). Thresholds roughly match broadcast "lap time analysis" graphics.
export const FULL_THROTTLE = 0.98; // throttle 0..1
export const HEAVY_BRAKING = 0.6; // brake 0..1
export const CORNERING_G = 1.5; // |lateral g|
const MIN_SAMPLES = 30; // a lap with fewer samples (e.g. joined late) isn't shown as "last lap"

export interface LapShare {
  fullThrottle: number; // 0..100
  heavyBraking: number;
  cornering: number;
}

interface Acc {
  lap: number;
  n: number;
  thr: number;
  brk: number;
  cor: number;
}

function share(a: Acc): LapShare {
  return {
    fullThrottle: (a.thr / a.n) * 100,
    heavyBraking: (a.brk / a.n) * 100,
    cornering: (a.cor / a.n) * 100,
  };
}

export class LapShareTracker {
  private readonly current = new Map<string, Acc>();
  private readonly last = new Map<string, LapShare>();

  add(frame: RigFrame): void {
    const lap = frame.lap;
    if (frame.state !== "driving" || !lap || lap.distance_m < 0) return;
    let acc = this.current.get(frame.rig_id);
    if (!acc || acc.lap !== lap.number) {
      if (acc && acc.n >= MIN_SAMPLES && lap.number === acc.lap + 1) this.last.set(frame.rig_id, share(acc));
      acc = { lap: lap.number, n: 0, thr: 0, brk: 0, cor: 0 };
      this.current.set(frame.rig_id, acc);
    }
    acc.n += 1;
    if ((frame.throttle ?? 0) >= FULL_THROTTLE) acc.thr += 1;
    if ((frame.brake ?? 0) >= HEAVY_BRAKING) acc.brk += 1;
    if (Math.abs(frame.car?.g_lat ?? 0) >= CORNERING_G) acc.cor += 1;
  }

  /** This lap so far, or null before the first sample of a lap. */
  thisLap(rigId: string): LapShare | null {
    const acc = this.current.get(rigId);
    return acc && acc.n > 0 ? share(acc) : null;
  }

  lastLap(rigId: string): LapShare | null {
    return this.last.get(rigId) ?? null;
  }

  clear(): void {
    this.current.clear();
    this.last.clear();
  }
}
