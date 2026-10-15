import { describe, expect, test } from "vitest";
import { MockHub } from "../mock/sim";
import { DashboardStore } from "../state/store";
import { rigName } from "./Attract";
import { MULTIVIEW_MAX, multiviewGrid } from "./Live";

describe("MULTIVIEW", () => {
  test("grids for up to 12 rigs: 1, 2, 2x2, 3x2, 4x2, 4x3", () => {
    const grids = Array.from({ length: 14 }, (_, i) => multiviewGrid(i + 1));
    expect(grids).toEqual(["1", "2", "4", "4", "6", "6", "8", "8", "12", "12", "12", "12", "12", "12"]);
    expect(MULTIVIEW_MAX).toBe(12);
  });

  test("the mock can drive 12 rigs, each with its own colour", () => {
    const hub = new MockHub({ ...new MockHub().options, rigs: 12, offlineRig: false });
    const snap = hub.snapshot();
    if (snap.type !== "snapshot") throw new Error("expected a snapshot");
    expect(snap.rigs).toHaveLength(12);
    expect(new Set(snap.rigs.map((r) => r.colour)).size).toBe(12);
  });
});

describe("rig labels on the TV", () => {
  test("a rig's name, never its id (its network address)", () => {
    const store = new DashboardStore("hub");
    store.dispatch(new MockHub().snapshot());
    const rig = store.getState().rigs[0]!;
    expect(rigName(store.getState(), rig.rig_id)).toBe(rig.name);
    expect(rigName(store.getState(), "192.168.1.50:20777")).toBe("Rig");
  });
});
