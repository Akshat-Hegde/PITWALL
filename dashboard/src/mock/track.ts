// Synthetic circuit for the mock data source: a smooth polar curve (r > 0, so it never crosses
// itself) with a physically plausible speed profile derived from its curvature.

export interface MockTrack {
  points: [number, number][];
  cum: number[]; // distance from the start line at each point (metres)
  length: number;
  speed: number[]; // reference speed at each point (m/s)
  sectorStarts: [number, number, number]; // point indices
  sectorDistances: [number, number, number]; // metres
}

const TARGET_LENGTH_M = 5200;
const LATERAL_GRIP = 20; // m/s^2: effective grip for this simplified model (gives ~86 s laps, 110 km/h hairpins)
const ACCEL = 11; // m/s^2
const BRAKE = 38; // m/s^2
const V_MIN = 20; // m/s (~72 km/h)
const V_MAX = 92; // m/s (~330 km/h)

export function buildTrack(n = 720): MockTrack {
  const raw: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const t = (2 * Math.PI * i) / n;
    // Low harmonics give the overall shape, high ones the tight corners. Amplitudes sum < 1, so r > 0.
    const r = 1 + 0.18 * Math.sin(2 * t + 0.4) + 0.1 * Math.sin(3 * t + 1.3) + 0.08 * Math.sin(6 * t + 0.7)
      + 0.05 * Math.sin(9 * t + 2.1) + 0.035 * Math.sin(13 * t + 0.3);
    raw.push([r * Math.cos(t), 0.62 * r * Math.sin(t)]);
  }
  let rawLength = 0;
  for (let i = 0; i < n; i++) rawLength += dist(raw[i]!, raw[(i + 1) % n]!);
  const scale = TARGET_LENGTH_M / rawLength;
  const points = raw.map(([x, z]) => [x * scale, z * scale] as [number, number]);

  const cum = [0];
  for (let i = 1; i < n; i++) cum.push(cum[i - 1]! + dist(points[i - 1]!, points[i]!));
  const length = cum[n - 1]! + dist(points[n - 1]!, points[0]!);

  // Curvature from the circle through neighbouring points, lightly smoothed.
  const kappa = points.map((_, i) => curvature(points[(i - 2 + n) % n]!, points[i]!, points[(i + 2) % n]!));
  const smooth = kappa.map((_, i) => {
    let s = 0;
    for (let k = -3; k <= 3; k++) s += kappa[(i + k + n) % n]!;
    return s / 7;
  });

  // Grip-limited speed, then acceleration (forward) and braking (backward) limits, run twice
  // around the loop so the start/finish wrap is consistent.
  const speed = smooth.map((k) => Math.min(V_MAX, Math.max(V_MIN, Math.sqrt(LATERAL_GRIP / Math.max(k, 1e-6)))));
  for (let pass = 0; pass < 2; pass++) {
    for (let j = 1; j <= n; j++) {
      const i = j % n;
      const prev = (j - 1) % n;
      const ds = dist(points[prev]!, points[i]!);
      speed[i] = Math.min(speed[i]!, Math.sqrt(speed[prev]! ** 2 + 2 * ACCEL * ds));
    }
    for (let j = n - 1; j >= 0; j--) {
      const next = (j + 1) % n;
      const ds = dist(points[j]!, points[next]!);
      speed[j] = Math.min(speed[j]!, Math.sqrt(speed[next]! ** 2 + 2 * BRAKE * ds));
    }
  }

  const s2 = indexAtDistance(cum, length / 3);
  const s3 = indexAtDistance(cum, (2 * length) / 3);
  return {
    points,
    cum,
    length,
    speed,
    sectorStarts: [0, s2, s3],
    sectorDistances: [0, cum[s2]!, cum[s3]!],
  };
}

function dist(a: [number, number], b: [number, number]): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

function curvature(a: [number, number], b: [number, number], c: [number, number]): number {
  const area2 = Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
  const d = dist(a, b) * dist(b, c) * dist(a, c);
  return d > 0 ? (2 * area2) / d : 0;
}

/** Last point index whose distance is <= d. */
export function indexAtDistance(cum: number[], d: number): number {
  let lo = 0;
  let hi = cum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (cum[mid]! <= d) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Position and reference speed at a distance into the lap (wraps; negative = before the line). */
export function sampleTrack(track: MockTrack, distance: number): { x: number; z: number; speed: number } {
  const n = track.points.length;
  const d = ((distance % track.length) + track.length) % track.length;
  const i = indexAtDistance(track.cum, d);
  const j = (i + 1) % n;
  const segStart = track.cum[i]!;
  const segEnd = j === 0 ? track.length : track.cum[j]!;
  const k = segEnd > segStart ? (d - segStart) / (segEnd - segStart) : 0;
  const a = track.points[i]!;
  const b = track.points[j]!;
  return {
    x: a[0] + (b[0] - a[0]) * k,
    z: a[1] + (b[1] - a[1]) * k,
    speed: track.speed[i]! + (track.speed[j]! - track.speed[i]!) * k,
  };
}

/** Lap time at the reference speed profile (ms). */
export function referenceLapMs(track: MockTrack): number {
  const n = track.points.length;
  let t = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const ds = (j === 0 ? track.length : track.cum[j]!) - track.cum[i]!;
    t += ds / ((track.speed[i]! + track.speed[j]!) / 2);
  }
  return t * 1000;
}
