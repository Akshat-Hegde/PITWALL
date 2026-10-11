import { describe, expect, test } from "vitest";
import type { RigFrame } from "../schema";
import { LapTraceTracker, MINI_SECTORS, fasterPerMini, rateMini, speedZones } from "./laptrace";

const LENGTH = 4800;

function frame(rig: string, lap: number, d: number, t: number, opts: Partial<{ last: number | null; valid: boolean;
  speed: number }> = {}): RigFrame {
  return {
    rig_id: rig, state: "driving", last_seen_ms: 0, driver: rig,
    session: { session_id: "s", track_key: "trk", track_name: "Trk", track_length_m: LENGTH, session_type: "Time Trial" },
    position: null, speed_kph: opts.speed ?? 200, gear: 5, throttle: 1, brake: 0, rpm: 10000, tyre: null,
    lap: { number: lap, distance_m: d, current_ms: t, last_ms: opts.last ?? null, valid: opts.valid ?? true,
      sector: 0, sectors: [null, null, null], last_sectors: null },
    best: null,
  };
}

/** Drive a lap at constant speed (m/s), 15 Hz, then cross the line. */
function driveLap(tr: LapTraceTracker, rig: string, lap: number, mps: number, opts: { slowFrom?: number } = {}) {
  let t = 0;
  let d = 0;
  while (d < LENGTH) {
    tr.add(frame(rig, lap, d, t));
    const v = opts.slowFrom !== undefined && d >= opts.slowFrom ? mps * 0.8 : mps;
    d += v / 15;
    t += 1000 / 15;
  }
  const lapMs = Math.round(t - ((d - LENGTH) / mps) * 1000);
  tr.add(frame(rig, lap + 1, d - LENGTH, t - lapMs, { last: lapMs }));
  return lapMs;
}

describe("lap traces", () => {
  test("a clean lap gives 24 mini-sectors that add up to the lap time", () => {
    const tr = new LapTraceTracker();
    const lapMs = driveLap(tr, "a", 1, 60);
    const best = tr.bestLap("a", "trk")!;
    expect(best.minis).toHaveLength(MINI_SECTORS);
    expect(Math.abs(best.minis.reduce((s, m) => s + m, 0) - lapMs)).toBeLessThan(2);
    expect(best.share.fullThrottle).toBe(100);
  });

  test("a lap picked up halfway or with a flashback doesn't count", () => {
    const tr = new LapTraceTracker();
    tr.add(frame("a", 1, 2400, 40_000));
    tr.add(frame("a", 1, 4790, 79_800));
    tr.add(frame("a", 2, 5, 100, { last: 80_000 }));
    expect(tr.lastLap("a", "trk")).toBeNull();
    tr.add(frame("a", 2, 900, 15_000));
    tr.add(frame("a", 2, 600, 10_000)); // flashback
    expect(tr.liveMinis("a")!.ratings.every((r) => r === "invalid" || r === "purple")).toBe(true);
  });

  test("live mini-sectors: purple when fastest, green own best, yellow slower", () => {
    const tr = new LapTraceTracker();
    driveLap(tr, "a", 1, 60); // a sets the reference
    driveLap(tr, "b", 1, 50);
    // b's second lap: slower than a, but faster than its own best for the first few
    for (let d = 4, t = 80; d < 1500; d += 50.5 / 15, t += 1000 / 15) tr.add(frame("b", 2, d, t));
    const ratings = tr.liveMinis("b")!.ratings;
    expect(ratings.length).toBeGreaterThan(5);
    expect(new Set(ratings)).toEqual(new Set(["green"]));
    expect(rateMini(100, true, 110, 120)).toBe("purple");
    expect(rateMini(115, true, 110, 120)).toBe("green");
    expect(rateMini(125, true, 110, 120)).toBe("yellow");
    expect(rateMini(90, false, 110, 120)).toBe("invalid");
  });

  test("who is faster per mini-sector", () => {
    const tr = new LapTraceTracker();
    driveLap(tr, "a", 1, 60, { slowFrom: LENGTH / 2 });
    driveLap(tr, "b", 1, 55);
    const who = fasterPerMini(tr.bestLap("a", "trk")!, tr.bestLap("b", "trk")!);
    expect(who.slice(0, 10).every((w) => w === "a")).toBe(true);
    expect(who.slice(14).every((w) => w === "b")).toBe(true);
  });

  test("speed zones are the corners, classed by minimum speed", () => {
    const speed = Array.from({ length: 200 }, (_, i) => {
      if (Math.abs(i - 40) < 5) return 90 + Math.abs(i - 40) * 30; // hairpin
      if (Math.abs(i - 120) < 5) return 170 + Math.abs(i - 120) * 20;
      if (Math.abs(i - 170) < 5) return 240 + Math.abs(i - 170) * 15;
      return 300;
    });
    const zones = speedZones(speed);
    expect(zones.map((z) => z.kind)).toEqual(["low", "medium", "high"]);
    expect(zones[0]!.at).toBeCloseTo(40.5 / 200);
  });
});

describe("mini-sector owners (map colours)", () => {
  test("the rig fastest through each mini-sector owns it, from clean laps valid or not", async () => {
    const { LapTraceTracker, MINI_SECTORS } = await import("./laptrace");
    const tracker = new LapTraceTracker();
    const L = 2400;
    const lap = (rig: string, n: number, msPerMetre: (d: number) => number, valid: boolean) => {
      let t = 0;
      for (let d = 0; d <= L - 10; d += 10) {
        tracker.add({ rig_id: rig, state: "driving", session: { track_key: "T", track_length_m: L },
          lap: { number: n, distance_m: d, current_ms: Math.round(t), valid, last_ms: null }, speed_kph: 200 } as never);
        t += 10 * msPerMetre(d);
      }
      tracker.add({ rig_id: rig, state: "driving", session: { track_key: "T", track_length_m: L },
        lap: { number: n + 1, distance_m: 1, current_ms: 5, valid: true, last_ms: Math.round(t) }, speed_kph: 200 } as never);
    };
    lap("a", 1, (d) => (d < L / 2 ? 10 : 20), false);   // fast in the first half, invalid lap
    lap("b", 1, (d) => (d < L / 2 ? 20 : 10), true);    // fast in the second half
    const owners = tracker.miniOwners("T")!;
    expect(owners).toHaveLength(MINI_SECTORS);
    expect(owners[2]).toBe("a");
    expect(owners[MINI_SECTORS - 3]).toBe("b");
  });
});
