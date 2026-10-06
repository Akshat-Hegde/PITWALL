// Position history per rig, kept outside React so the map canvas can draw at display refresh rate.
// Dots are drawn slightly in the past (one frame interval) and interpolated between received samples.

export interface Sample {
  t: number; // local receive time, ms (performance.now())
  x: number;
  z: number;
}

export class TrailBuffer {
  private readonly trails = new Map<string, Sample[]>();

  constructor(private readonly keepMs = 8000) {}

  add(rigId: string, t: number, x: number, z: number): void {
    let trail = this.trails.get(rigId);
    if (!trail) {
      trail = [];
      this.trails.set(rigId, trail);
    }
    trail.push({ t, x, z });
    const cutoff = t - this.keepMs;
    let drop = 0;
    while (drop < trail.length && trail[drop]!.t < cutoff) drop++;
    if (drop > 0) trail.splice(0, drop);
  }

  clear(rigId?: string): void {
    if (rigId === undefined) this.trails.clear();
    else this.trails.delete(rigId);
  }

  get(rigId: string): readonly Sample[] {
    return this.trails.get(rigId) ?? [];
  }

  rigIds(): string[] {
    return [...this.trails.keys()];
  }

  /** Interpolated position at time t (clamped to the newest sample, no extrapolation). */
  positionAt(rigId: string, t: number): { x: number; z: number } | null {
    return interpolate(this.get(rigId), t);
  }
}

export function interpolate(samples: readonly Sample[], t: number): { x: number; z: number } | null {
  const n = samples.length;
  if (n === 0) return null;
  const last = samples[n - 1]!;
  if (t >= last.t) return { x: last.x, z: last.z };
  const first = samples[0]!;
  if (t <= first.t) return { x: first.x, z: first.z };
  // Samples are time-ordered; search from the end since t is usually near "now".
  for (let i = n - 1; i > 0; i--) {
    const a = samples[i - 1]!;
    const b = samples[i]!;
    if (t >= a.t) {
      const span = b.t - a.t;
      const k = span > 0 ? (t - a.t) / span : 1;
      return { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k };
    }
  }
  return { x: first.x, z: first.z };
}
