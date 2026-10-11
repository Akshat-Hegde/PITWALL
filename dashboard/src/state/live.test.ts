import { describe, expect, test } from "vitest";
import type { RigFrame } from "../schema";
import { LiveTelemetry, inputAt, timeAt } from "./live";

const LENGTH = 1000;

function frame(lap: number, d: number, t: number, opts: { valid?: boolean; speed?: number; lastMs?: number | null } = {}): RigFrame {
  return {
    rig_id: "r1", state: "driving", last_seen_ms: 0, driver: "Maya",
    session: { session_id: "s", track_key: "F1:7", track_name: "Silverstone", track_length_m: LENGTH, session_type: null },
    position: { x: 0, z: 0 }, speed_kph: opts.speed ?? 200, gear: 6, throttle: 1, brake: 0, rpm: 10000, tyre: null,
    lap: { number: lap, distance_m: d, current_ms: t, last_ms: opts.lastMs ?? null, valid: opts.valid ?? true, sector: 0,
           sectors: [null, null, null], last_sectors: null },
    best: null, car: { steer: 0.5 } as RigFrame["car"],
  };
}

/** Drive a lap of LENGTH metres taking lapMs, 50 m per frame. */
function driveLap(live: LiveTelemetry, lap: number, lapMs: number, valid = true, startAt = 0) {
  for (let d = startAt; d < LENGTH; d += 50) live.add(frame(lap, d, (d / LENGTH) * lapMs, { valid }), lap * 100_000 + d);
}

describe("live telemetry", () => {
  test("delta to the driver's own best lap at the same distance", () => {
    const live = new LiveTelemetry();
    driveLap(live, 1, 60_000);
    expect(live.deltaToBest("r1")).toBeNull();                   // no full lap yet
    live.add(frame(2, 0, 0, { lastMs: 60_000 }), 200_000);
    live.add(frame(2, 500, 29_000), 200_100);                    // half way, 1 s up
    expect(live.deltaToBest("r1")).toBe(-1000);
    expect(live.speedTraces("r1")?.bestMs).toBe(60_000);
  });

  test("a lap joined late or cut by a flashback never becomes the reference", () => {
    const live = new LiveTelemetry();
    driveLap(live, 1, 60_000, true, 300);                        // joined at 300 m
    live.add(frame(2, 0, 0, { lastMs: 60_000 }), 1);
    expect(live.speedTraces("r1")?.best).toBeNull();
    driveLap(live, 2, 61_000);
    live.add(frame(2, 100, 3000), 2);                            // flashback to 100 m
    live.add(frame(3, 0, 0, { lastMs: 61_000 }), 3);
    expect(live.speedTraces("r1")?.best).toBeNull();
  });

  test("a valid lap beats an invalid one; an invalid clean lap is used until then", () => {
    const live = new LiveTelemetry();
    driveLap(live, 1, 58_000, false);
    live.add(frame(2, 0, 0, { lastMs: 58_000 }), 1);
    expect(live.speedTraces("r1")?.bestMs).toBe(58_000);
    driveLap(live, 2, 62_000, true);
    live.add(frame(3, 0, 0, { lastMs: 62_000 }), 2);
    expect(live.speedTraces("r1")?.bestMs).toBe(62_000);
  });

  test("interpolation between frames", () => {
    expect(timeAt({ d: [0, 100], t: [0, 2000], v: [0, 0] }, 25)).toBe(500);
    const s = inputAt([{ t: 0, thr: 0, brk: 1, steer: -1, speed: 100 }, { t: 100, thr: 1, brk: 0, steer: 1, speed: 200 }], 25);
    expect(s).toMatchObject({ thr: 0.25, brk: 0.75, steer: -0.5, speed: 125 });
  });
});

describe("lap rollover", () => {
  test("no delta while the new lap number arrives with the old lap's distance", () => {
    const live = new LiveTelemetry();
    driveLap(live, 1, 60_000);
    live.add(frame(2, 0, 0, { lastMs: 60_000 }), 1);
    live.add(frame(2, 990, 0), 2);                               // lap 2, distance not reset yet
    expect(live.deltaToBest("r1")).toBeNull();
  });
});
