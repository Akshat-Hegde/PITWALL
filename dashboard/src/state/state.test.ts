import { describe, expect, test } from "vitest";
import { chooseTrackKey } from "../App";
import { formatDelta, formatGear, formatLapTime, formatSector } from "../format";
import { emptyBounds, extend, fitBounds, project, toMapPlane } from "../map/geometry";
import { DEFAULT_MOCK_OPTIONS, MockHub } from "../mock/sim";
import type { HubMessage, LapRecord } from "../schema";
import { RECENT_LAPS_MAX, applyMessage, initialState } from "./reducer";
import { DashboardStore } from "./store";
import { TrailBuffer, interpolate } from "./trails";

function mockMessages(seconds: number): HubMessage[] {
  let clock = 1_791_300_000_000;
  const hub = new MockHub(DEFAULT_MOCK_OPTIONS, () => clock);
  const out: HubMessage[] = [hub.snapshot()];
  for (let t = 0; t < seconds * 15; t++) {
    clock += 67;
    out.push(...hub.step(1000 / 15));
  }
  return out;
}

describe("format", () => {
  test("lap times", () => {
    expect(formatLapTime(88123)).toBe("1:28.123");
    expect(formatLapTime(61005)).toBe("1:01.005");
    expect(formatLapTime(9123)).toBe("9.123");
    expect(formatLapTime(null)).toBe("–:––.–––");
    expect(formatSector(28011)).toBe("28.011");
  });

  test("deltas use a true minus sign", () => {
    expect(formatDelta(180)).toBe("+0.180");
    expect(formatDelta(-412)).toBe("−0.412");
    expect(formatDelta(0)).toBe("0.000");
    expect(formatDelta(-1234, 2)).toBe("−1.23");
    expect(formatDelta(null)).toBe("–");
  });

  test("gears", () => {
    expect([formatGear(-1), formatGear(0), formatGear(7), formatGear(null)]).toEqual(["R", "N", "7", "–"]);
  });
});

describe("reducer", () => {
  const msgs = mockMessages(200);
  const snapshot = msgs[0]!;

  test("snapshot replaces state and goes live", () => {
    let s = initialState("mock");
    s = applyMessage(s, snapshot, 0);
    expect(s.link).toBe("live");
    expect(s.rigs.map((r) => r.rig_id)).toEqual(["rig-1", "rig-2", "rig-3"]);
    expect(Object.keys(s.frames)).toHaveLength(3);
    // A second snapshot wipes laps collected since.
    const lap = msgs.find((m) => m.type === "lap_completed")!;
    s = applyMessage(s, lap, 1);
    expect(s.recentLaps).toHaveLength(1);
    s = applyMessage(s, { ...snapshot, recent_laps: [] } as HubMessage, 2);
    expect(s.recentLaps).toHaveLength(0);
  });

  test("applies a whole session without errors and keeps recent laps capped", () => {
    let s = initialState("mock");
    for (const m of msgs) s = applyMessage(s, m, 0);
    expect(s.leaderboards.today?.entries.length).toBeGreaterThan(0);
    expect(Object.keys(s.leaderboards)).toEqual(["today", "week", "all_time"]);
    expect(s.recentLaps.length).toBeLessThanOrEqual(RECENT_LAPS_MAX);
    expect(s.comparison).not.toBeNull();
  });

  test("unknown types are ignored", () => {
    const s = applyMessage(initialState("hub"), snapshot, 0);
    const next = applyMessage(s, { v: 1, type: "something_new", seq: 1, ts: 0 } as unknown as HubMessage, 1);
    expect(next).toBe(s);
  });

  test("another schema version stops rendering", () => {
    const s = applyMessage(initialState("hub"), { ...snapshot, v: 2 } as HubMessage, 0);
    expect(s.link).toBe("version_mismatch");
    expect(s.receivedVersion).toBe(2);
    expect(applyMessage(s, snapshot, 1).link).toBe("version_mismatch");
  });

  test("rig_info adds or replaces a rig", () => {
    let s = applyMessage(initialState("hub"), snapshot, 0);
    const renamed = { ...s.rigs[0]!, name: "Front window" };
    s = applyMessage(s, { v: 1, type: "rig_info", seq: 1, ts: 0, rig: renamed }, 0);
    expect(s.rigs[0]!.name).toBe("Front window");
    s = applyMessage(s, { v: 1, type: "rig_info", seq: 2, ts: 0, rig: { ...renamed, rig_id: "rig-9" } }, 0);
    expect(s.rigs).toHaveLength(4);
  });

  test("leaderboard messages fill boards by period; another track replaces them", () => {
    let s = applyMessage(initialState("hub"), { ...snapshot, leaderboards: [] } as HubMessage, 0);
    const board = (track: string, period: string): HubMessage => ({
      v: 1, type: "leaderboard", seq: 1, ts: 0,
      leaderboard: { track_key: track, track_name: null, period, since: null, entries: [] },
    });
    s = applyMessage(s, board("F1:7", "today"), 0);
    s = applyMessage(s, board("F1:7", "all_time"), 0);
    expect(Object.keys(s.leaderboards)).toEqual(["today", "all_time"]);
    s = applyMessage(s, board("F1:10", "week"), 0);
    expect(Object.entries(s.leaderboards).map(([p, b]) => [p, b!.track_key])).toEqual([["week", "F1:10"]]);
    expect(applyMessage(s, board("F1:10", "month"), 0)).toBe(s); // unknown period ignored
  });

  test("lap_completed puts the newest first", () => {
    let s = applyMessage(initialState("hub"), snapshot, 0);
    const lap = (n: number): HubMessage => ({
      v: 1, type: "lap_completed", seq: n, ts: 0,
      lap: { lap_number: n } as LapRecord,
    });
    s = applyMessage(s, lap(1), 0);
    s = applyMessage(s, lap(2), 0);
    expect(s.recentLaps.map((l) => l.lap_number)).toEqual([2, 1]);
  });
});

describe("store and trails", () => {
  test("store records positions of driving rigs and clears trails on a new snapshot", () => {
    const store = new DashboardStore("mock");
    const msgs = mockMessages(10);
    msgs.forEach((m, i) => store.dispatch(m, i * 67));
    expect(store.trails.get("rig-1").length).toBeGreaterThan(50);
    expect(store.trails.get("rig-3")).toHaveLength(0);
    store.dispatch(msgs[0]!, 99999);
    expect(store.trails.rigIds()).toEqual(["rig-1"]); // only positions from the new snapshot
  });

  test("trail buffer drops samples older than its window", () => {
    const t = new TrailBuffer(1000);
    for (let i = 0; i <= 30; i++) t.add("a", i * 100, i, 0);
    const kept = t.get("a");
    expect(kept[0]!.t).toBe(2000);
    expect(kept[kept.length - 1]!.t).toBe(3000);
  });

  test("interpolation between samples, clamped at the ends", () => {
    const samples = [
      { t: 0, x: 0, z: 0 },
      { t: 100, x: 10, z: 20 },
    ];
    expect(interpolate(samples, 50)).toEqual({ x: 5, z: 10 });
    expect(interpolate(samples, -10)).toEqual({ x: 0, z: 0 });
    expect(interpolate(samples, 500)).toEqual({ x: 10, z: 20 });
    expect(interpolate([], 0)).toBeNull();
  });
});

describe("map geometry", () => {
  test("display transform", () => {
    expect(toMapPlane(3, 4, { flip_x: false, flip_z: false, rotate_deg: 0 })).toEqual([3, 4]);
    expect(toMapPlane(3, 4, { flip_x: true, flip_z: true, rotate_deg: 0 })).toEqual([-3, -4]);
    const [x, y] = toMapPlane(1, 0, { flip_x: false, flip_z: false, rotate_deg: 90 });
    expect(x).toBeCloseTo(0);
    expect(y).toBeCloseTo(1);
  });

  test("fit keeps aspect ratio and centres", () => {
    const b = extend(extend(emptyBounds(), 0, 0), 200, 100);
    const fit = fitBounds(b, 1000, 1000, 100);
    expect(fit.scale).toBeCloseTo(4); // width-limited: 800 / 200
    const [x0, y0] = project(fit, 0, 0);
    const [x1, y1] = project(fit, 200, 100);
    expect([x0, x1]).toEqual([100, 900]);
    expect((y0 + y1) / 2).toBeCloseTo(500);
  });
});

describe("map track choice", () => {
  test("follows the track most driving rigs are on", () => {
    let s = initialState("mock");
    for (const m of mockMessages(20)) s = applyMessage(s, m, 0);
    expect(chooseTrackKey(s)).toBe("F1:900");
    expect(chooseTrackKey(initialState("hub"))).toBeNull();
  });
});

describe("session best", () => {
  test("is the fastest best lap on the shown track", async () => {
    const { sessionBest } = await import("../App");
    let s = initialState("mock");
    for (const m of mockMessages(400)) s = applyMessage(s, m, 0);
    const bests = Object.values(s.frames).map((f) => f.best?.lap_ms).filter((v): v is number => v != null);
    expect(bests.length).toBe(2);
    expect(sessionBest(s, "F1:900")).toBe(Math.min(...bests));
    expect(sessionBest(s, "F1:1")).toBeNull();
  });
});

describe("leaderboard paging", () => {
  test("ten per page, wrapping, with the range shown", async () => {
    const { pageCount, pageSlice, BOARD_PAGE_SIZE } = await import("../components/LeaderboardPanel");
    expect(BOARD_PAGE_SIZE).toBe(10);
    const fourteen = Array.from({ length: 14 }, (_, i) => i + 1);
    expect([pageCount(0), pageCount(10), pageCount(11), pageCount(14)]).toEqual([1, 1, 2, 2]);
    expect(pageSlice(fourteen, 0)).toMatchObject({ first: 1, last: 10, page: 0 });
    expect(pageSlice(fourteen, 1)).toMatchObject({ items: [11, 12, 13, 14], first: 11, last: 14 });
    expect(pageSlice(fourteen, 2).page).toBe(0); // wraps back to the top
    expect(pageSlice([], 3)).toMatchObject({ items: [], first: 0, last: 0 });
  });

  test("mock board=N adds earlier drivers, ranked with gaps", () => {
    const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, pastDrivers: 12 }, () => 0);
    const board = hub.snapshot().leaderboards[0]!;
    expect(board.entries).toHaveLength(12);
    board.entries.forEach((e, i) => {
      expect(e.rank).toBe(i + 1);
      expect(e.gap_ms).toBe(e.lap_ms - board.entries[0]!.lap_ms);
    });
    expect(new MockHub(DEFAULT_MOCK_OPTIONS, () => 0).snapshot().leaderboards).toEqual([]);
  });
});

describe("path trace and map orientation override", () => {
  test("path downsamples, splits on jumps and caps its size", async () => {
    const { PathTrace, PATH_MAX_POINTS } = await import("./paths");
    const p = new PathTrace();
    for (let i = 0; i < 100; i++) p.add("F1:7", "a", i * 2, 0); // 2 m steps: every 4th point kept
    expect(p.segments("F1:7")[0]!.length).toBe(25);
    p.add("F1:7", "a", 5000, 0); // flashback-sized jump: new segment
    p.add("F1:7", "a", 5010, 0);
    expect(p.segments("F1:7").length).toBe(2);
    for (let i = 0; i < PATH_MAX_POINTS * 2; i++) p.add("F1:9", "b", i * 10, 0);
    const total = p.segments("F1:9").reduce((n, s) => n + s.length, 0);
    expect(total).toBe(PATH_MAX_POINTS);
    expect(p.segments("F1:9")[0]![0]![0]).toBe(PATH_MAX_POINTS * 10); // oldest points dropped
    expect(p.segments("F1:1")).toEqual([]);
  });

  test("?map= parsing", async () => {
    const { displayFromQuery, describeDisplay } = await import("../map/geometry");
    expect(displayFromQuery(new URLSearchParams(""))).toBeNull();
    const d = displayFromQuery(new URLSearchParams("map=flipz,rot90"))!;
    expect(d).toEqual({ flip_x: false, flip_z: true, rotate_deg: 90 });
    expect(describeDisplay(d)).toBe("flip z, rotated 90°");
    expect(displayFromQuery(new URLSearchParams("map="))).toEqual({ flip_x: false, flip_z: false, rotate_deg: 0 });
  });
});
