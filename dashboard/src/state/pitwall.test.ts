import { describe, expect, test } from "vitest";
import type { LeaderboardEntry, LiveLap, StoryLap } from "../schema";
import {
  deltaTo, fmtPred, headlineSize, headlines, predictedPosition, refFromMinis, refFromTrace, storyChart, towerRows,
} from "./pitwall";

const entry = (driver: string, lap_ms: number, sectors: [number, number, number] | null = null): LeaderboardEntry => ({
  rank: 0, rig_id: `rig-${driver}`, rig_name: "Rig", driver, lap_ms, sectors_ms: sectors, gap_ms: 0, tyre: null,
  lap_number: 1, set_at: 0,
});
const lap = (d: number, t: number): LiveLap => ({
  number: 3, distance_m: d, current_ms: t, last_ms: null, valid: true, sector: 0, sectors: [null, null, null], last_sectors: null,
});

describe("reference laps", () => {
  test("record from mini-sector times: time at distance and the ghost's distance at a time", () => {
    const ref = refFromMinis("record", new Array(24).fill(4000), 2400)!;
    expect(ref.lapMs).toBe(96_000);
    expect(ref.timeAt(1200)).toBe(48_000);
    expect(ref.distAt(24_000)).toBe(600);
    expect(refFromMinis("record", [1, 0, 2], 100)).toBeNull();
  });

  test("delta to the reference at the same distance; none at the line rollover", () => {
    const ref = refFromTrace("pb", { d: [0, 1000], t: [0, 60_000], v: [0, 0] }, 1000, 60_000)!;
    expect(deltaTo(ref, lap(500, 29_000))).toBe(-1000);
    expect(deltaTo(ref, lap(990, 0))).toBeNull();      // new lap number with the old lap's distance
    expect(deltaTo(ref, lap(-20, 100))).toBeNull();
    expect(deltaTo(null, lap(500, 29_000))).toBeNull();
  });
});

describe("tower", () => {
  const board = [entry("Rahul K", 87_402, [28_000, 36_000, 23_402]), entry("Akki", 87_968, [28_300, 35_900, 23_768]),
    entry("Priya S", 88_115, [28_500, 36_500, 23_115]), entry("Dev M", 89_240, [29_000, 37_000, 23_240])];

  test("the ghost row slots in where the predicted lap would place it", () => {
    const rows = towerRows(board, (e) => (e.driver === "Priya S" ? "#FF8A1F" : null),
      { name: "Priya S", colour: "#FF8A1F", predMs: 87_090, sectors: ["p", "n", "n"] });
    expect(rows.map((r) => r.pos)).toEqual(["P1", "1", "2", "3", "4"]);
    expect(rows[0]).toMatchObject({ ghost: true, name: "PRIYA S", sub: "P1 ON THIS LAP", gapMs: 87_090 - 87_402 });
    expect(rows[1]!.leader && rows[1]!.colour === null).toBe(true);
    expect(rows[3]!.colour).toBe("#FF8A1F");
    expect(predictedPosition(board, 88_000)).toBe(3);
  });

  test("sector colours: purple fastest on the board, green quicker than the median", () => {
    const rows = towerRows(board, () => null, null);
    expect(rows[0]!.sectors).toEqual(["p", "g", "y"]);
    expect(rows[1]!.sectors).toEqual(["g", "p", "y"]);
  });

  test("at most eight board rows besides the ghost", () => {
    const many = Array.from({ length: 12 }, (_, i) => entry(`D${i}`, 90_000 + i * 100));
    expect(towerRows(many, () => null, null)).toHaveLength(9);
    expect(towerRows(many, () => null, { name: "X", colour: "#fff", predMs: 99_999, sectors: [] })).toHaveLength(9);
  });
});

describe("headlines", () => {
  test("delta after a sector, the predicted lap and a chaser, with neutral pronouns", () => {
    const h = headlines({
      focus: { name: "PRIYA S", delta: -310, sectorsDone: 2, vsRecord: true, predMs: 87_092, predPos: 1 },
      chaser: { name: "AKKI", delta: 420 }, record: { holder: "RAHUL K", lapMs: 87_402 }, focusBestMs: 88_115,
    });
    const text = h.map((line) => line.map(([t]) => t).join(""));
    expect(text).toEqual([
      "PRIYA S IS 0.31 s UP ON TODAY'S RECORD AFTER SECTOR 2",
      "PRIYA S IS ON FOR 1:27.09 — THAT WOULD BE A NEW RECORD",
      "AKKI CHASING THEIR BEST — 0.42 s TO FIND",
      "TODAY'S RECORD: RAHUL K 1:27.402 — 0.71 s STILL TO FIND",
    ]);
    expect(h[1]![1]).toEqual(["1:27.09", "p"]);
    expect(fmtPred(87_092)).toBe("1:27.09");
    expect(headlineSize(h[0]!)).toBeLessThanOrEqual(62);
  });

  test("something to say when nobody is driving", () => {
    expect(headlines({ focus: null, chaser: null, record: null, focusBestMs: null })[0]![0]![0]).toContain("SET A LAP");
  });
});

describe("session story", () => {
  test("a line per driver, their best lap ringed, invalid laps hollow, reference lines", () => {
    const now = 1_000_000_000;
    const laps: StoryLap[] = [
      { rig_id: "r1", driver: "Akki", lap_ms: 90_000, valid: true, out_lap: false, completed_at: now - 600_000 },
      { rig_id: "r1", driver: "Akki", lap_ms: 88_000, valid: true, out_lap: false, completed_at: now - 500_000 },
      { rig_id: "r1", driver: "Akki", lap_ms: 87_500, valid: false, out_lap: false, completed_at: now - 400_000 },
      { rig_id: "r2", driver: "Dev", lap_ms: 89_000, valid: true, out_lap: false, completed_at: now - 300_000 },
      { rig_id: "r2", driver: "Dev", lap_ms: 99_000, valid: true, out_lap: true, completed_at: now - 200_000 },
    ];
    const c = storyChart(laps, now, (l) => (l.rig_id === "r1" ? "#33C8FF" : "#5B8CFF"), [{ ms: 87_402, label: "REC", colour: "#B15CFF" }]);
    expect(c.lines).toHaveLength(2);
    expect(c.dots).toHaveLength(4);                                   // the out lap is left out
    expect(c.dots.filter((d) => d.stroke === "#fff")).toHaveLength(2); // one best lap per driver
    expect(c.dots.find((d) => d.fill === "#0B0C0F")).toBeDefined();  // the invalid lap
    expect(c.names.map((n) => n.text).sort()).toEqual(["AKKI", "DEV"]);
    expect(c.yTicks[0]!.label).toBe("1:27");
    expect(c.nowX).toBeLessThan(1098);
    expect(c.refs[0]!.y).toBeGreaterThan(10);
  });
});
