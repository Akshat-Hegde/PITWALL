// Longer, downsampled history of where each rig has driven on each track. Drawn faintly on the
// map while no track outline exists, so the track's shape (and the map orientation) shows up
// before lap tracking can produce a proper outline.

export const PATH_MIN_STEP_M = 8; // skip points closer than this to the previous one
export const PATH_JUMP_M = 200; // a bigger jump (flashback, restart) starts a new segment
export const PATH_MAX_POINTS = 3000; // per rig and track: ~24 km, about four laps

export type Segment = [number, number][];

export class PathTrace {
  // trackKey -> rigId -> segments
  private readonly tracks = new Map<string, Map<string, Segment[]>>();

  add(trackKey: string, rigId: string, x: number, z: number): void {
    let rigs = this.tracks.get(trackKey);
    if (!rigs) this.tracks.set(trackKey, (rigs = new Map()));
    let segments = rigs.get(rigId);
    if (!segments) rigs.set(rigId, (segments = [[]]));
    const current = segments[segments.length - 1]!;
    const last = current[current.length - 1];
    if (last) {
      const d = Math.hypot(x - last[0], z - last[1]);
      if (d < PATH_MIN_STEP_M) return;
      if (d > PATH_JUMP_M) {
        segments.push([[x, z]]);
        this.trim(segments);
        return;
      }
    }
    current.push([x, z]);
    this.trim(segments);
  }

  private trim(segments: Segment[]): void {
    let total = segments.reduce((n, s) => n + s.length, 0);
    while (total > PATH_MAX_POINTS && segments.length > 0) {
      const first = segments[0]!;
      const drop = Math.min(first.length, total - PATH_MAX_POINTS);
      first.splice(0, drop);
      total -= drop;
      if (first.length === 0 && segments.length > 1) segments.shift();
    }
  }

  segments(trackKey: string): Segment[] {
    const rigs = this.tracks.get(trackKey);
    if (!rigs) return [];
    return [...rigs.values()].flat().filter((s) => s.length > 1);
  }

  clear(): void {
    this.tracks.clear();
  }
}
