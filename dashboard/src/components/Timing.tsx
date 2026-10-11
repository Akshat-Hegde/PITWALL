import type { RigInfo } from "../schema";
import type { DashboardState } from "../state/reducer";

/** Rigs in running order: best lap on the shown track first, then the rest in rig order. */
export function runningOrder(state: DashboardState, trackKey: string | null): { rig: RigInfo; position: number | null }[] {
  const best = (rig: RigInfo) => {
    const f = state.frames[rig.rig_id];
    return f && f.session.track_key === trackKey && f.best ? f.best.lap_ms : null;
  };
  const sorted = state.rigs
    .map((rig, i) => ({ rig, i, ms: best(rig) }))
    .sort((a, b) => (a.ms ?? Infinity) - (b.ms ?? Infinity) || a.i - b.i);
  return sorted.map(({ rig, ms }, i) => ({ rig, position: ms == null ? null : i + 1 }));
}
