import { describe, expect, test } from "vitest";
import { findBattle } from "./components/Battle";
import type { DashboardState } from "./state/reducer";

type Car = { id: string; best: number; last: number | null; track?: string };

function state(cars: Car[], live?: { rig: string; ref: string; ms: number }): DashboardState {
  return {
    rigs: cars.map((c) => ({ rig_id: c.id, name: c.id, colour: "#fff" })),
    frames: Object.fromEntries(cars.map((c) => [c.id, {
      state: "driving",
      driver: c.id,
      session: { track_key: c.track ?? "t" },
      best: { lap_ms: c.best },
      lap: { last_ms: c.last },
    }])),
    comparison: live
      ? { rigs: [{ rig_id: live.rig, reference_rig_id: live.ref, live_delta_ms: live.ms }] }
      : null,
  } as unknown as DashboardState;
}

describe("battle", () => {
  test("picks the two closest best laps; leader is the faster one", () => {
    const b = findBattle(state([
      { id: "a", best: 80_000, last: 81_000 },
      { id: "b", best: 85_000, last: 86_000 },
      { id: "c", best: 85_300, last: 85_500 },
    ]), "t")!;
    expect([b.leader.rigId, b.chaser.rigId, b.gapMs]).toEqual(["b", "c", 300]);
  });

  test("rate per lap compares last laps: negative means the chaser is catching", () => {
    const b = findBattle(state([
      { id: "a", best: 80_000, last: 81_000 },
      { id: "b", best: 80_500, last: 80_600 },
    ], { rig: "b", ref: "a", ms: 120 }), "t")!;
    expect(b.ratePerLapMs).toBe(-400);
    expect(b.liveMs).toBe(120);
  });

  test("needs two cars with a best lap on the same track", () => {
    expect(findBattle(state([{ id: "a", best: 80_000, last: null }]), "t")).toBeNull();
    expect(findBattle(state([
      { id: "a", best: 80_000, last: null },
      { id: "b", best: 81_000, last: null, track: "other" },
    ]), "t")).toBeNull();
    const b = findBattle(state([{ id: "a", best: 80_000, last: null }, { id: "b", best: 81_000, last: 82_000 }]), "t")!;
    expect(b.ratePerLapMs).toBeNull();
  });
});
