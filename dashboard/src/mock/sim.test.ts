import { describe, expect, test } from "vitest";
import type { HubMessage, LapRecord, Leaderboard } from "../schema";
import { validateMessage } from "../testing/validate";
import { DEFAULT_MOCK_OPTIONS, MockHub, mockOptionsFromQuery, type MockOptions } from "./sim";
import { buildTrack, referenceLapMs } from "./track";

const TICK_MS = 1000 / 15;

function run(minutes: number, options: Partial<MockOptions> = {}) {
  let clock = 1_791_300_000_000;
  const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, ...options }, () => clock);
  const messages: HubMessage[] = [hub.snapshot()];
  const ticks = Math.round((minutes * 60_000) / TICK_MS);
  for (let i = 0; i < ticks; i++) {
    clock += Math.round(TICK_MS);
    messages.push(...hub.step(TICK_MS));
  }
  return messages;
}

const fifteenMinutes = run(15);
const laps = fifteenMinutes.filter((m) => m.type === "lap_completed").map((m) => m.lap as LapRecord);

describe("mock hub follows the v1 schema", () => {
  test("every message validates", () => {
    const problems = fifteenMinutes.flatMap((m) => validateMessage(m).map((e) => `seq ${m.seq}: ${e}`));
    expect(problems.slice(0, 10)).toEqual([]);
  });

  test("seq starts at 0 with the snapshot and increases by 1", () => {
    expect(fifteenMinutes[0]!.type).toBe("snapshot");
    fifteenMinutes.forEach((m, i) => expect(m.seq).toBe(i));
  });

  test("frames list every rig, including the offline one", () => {
    const frames = fifteenMinutes.filter((m) => m.type === "frame");
    for (const f of frames) expect(f.rigs.map((r) => r.rig_id)).toEqual(["rig-1", "rig-2", "rig-3"]);
    const last = frames[frames.length - 1]!;
    expect(last.rigs.find((r) => r.rig_id === "rig-3")!.state).toBe("no_data");
  });

  test("second rig starts in the menu, then drives", () => {
    const frames = fifteenMinutes.filter((m) => m.type === "frame");
    expect(frames[0]!.rigs[1]!.state).toBe("in_menu_paused");
    expect(frames[0]!.rigs[1]!.position).toBeNull();
    expect(frames[frames.length - 1]!.rigs[1]!.state).toBe("driving");
  });
});

describe("mock laps are plausible", () => {
  test("reference lap time is a believable F1 lap", () => {
    const seconds = referenceLapMs(buildTrack()) / 1000;
    expect(seconds).toBeGreaterThan(70);
    expect(seconds).toBeLessThan(110);
  });

  test("laps complete, sectors add up and some are invalid", () => {
    expect(laps.length).toBeGreaterThan(12);
    for (const lap of laps) {
      expect(lap.sectors_ms!.reduce((a, b) => a + b, 0)).toBe(lap.lap_ms);
      expect(lap.lap_ms).toBeGreaterThan(60_000);
      expect(lap.lap_ms).toBeLessThan(120_000);
    }
    expect(laps.some((l) => !l.valid)).toBe(true);
    expect(laps.some((l) => l.session_best)).toBe(true);
  });

  test("sector times are not quantised to the simulation tick", () => {
    // At 8x speed a tick is ~533 ms; splits must come from the exact crossing time.
    let clock = 0;
    const hub = new MockHub(DEFAULT_MOCK_OPTIONS, () => clock);
    const fast: HubMessage[] = [];
    for (let i = 0; i < 1500; i++) {
      clock += 533;
      fast.push(...hub.step(533));
    }
    const s2 = fast.filter((m) => m.type === "lap_completed").map((m) => m.lap.sectors_ms![1]);
    expect(s2.length).toBeGreaterThan(4);
    // Quantised splits would all be multiples of the tick; one can be by chance (1 in 533).
    expect(s2.filter((ms) => ms % 533 === 0 || ms % 1000 === 0).length).toBeLessThanOrEqual(1);
  });

  test("leaderboard: sorted, gaps to the leader, valid laps only", () => {
    const boards = fifteenMinutes.filter((m) => m.type === "leaderboard").map((m) => m.leaderboard as Leaderboard);
    expect(boards.length).toBeGreaterThan(0);
    const final = boards[boards.length - 1]!;
    const leader = final.entries[0]!.lap_ms;
    final.entries.forEach((e, i) => {
      expect(e.rank).toBe(i + 1);
      expect(e.gap_ms).toBe(e.lap_ms - leader);
      if (i > 0) expect(e.lap_ms).toBeGreaterThanOrEqual(final.entries[i - 1]!.lap_ms);
      const best = laps.filter((l) => l.rig_id === e.rig_id && l.valid).map((l) => l.lap_ms);
      expect(e.lap_ms).toBe(Math.min(...best));
    });
  });

  test("comparison appears once two rigs drive and gives live deltas", () => {
    const frames = fifteenMinutes.filter((m) => m.type === "frame");
    expect(frames[0]!.comparison).toBeNull();
    const withLive = frames.filter((f) => f.comparison?.rigs.some((r) => r.live_delta_ms !== null));
    expect(withLive.length).toBeGreaterThan(100);
    for (const f of withLive) {
      for (const r of f.comparison!.rigs) {
        if (r.live_delta_ms !== null) expect(Math.abs(r.live_delta_ms)).toBeLessThan(10_000);
      }
    }
  });

  test("same seed gives the same session", () => {
    const a = run(3).filter((m) => m.type === "lap_completed");
    const b = run(3).filter((m) => m.type === "lap_completed");
    expect(a).toEqual(b);
  });
});

describe("mock options", () => {
  test("outline=late sends the outline after the first valid lap", () => {
    const msgs = run(4, { outlineLate: true });
    const snapshot = msgs[0]!;
    expect(snapshot.type === "snapshot" && snapshot.outlines).toEqual([]);
    const outlineAt = msgs.findIndex((m) => m.type === "track_outline");
    const firstValid = msgs.findIndex((m) => m.type === "lap_completed" && m.lap.valid);
    expect(outlineAt).toBeGreaterThan(firstValid);
    expect(firstValid).toBeGreaterThan(0);
  });

  test("format mismatch and recorder warnings reach status", () => {
    const msgs = run(0.1, { formatMismatch: true, recorder: "stopped" });
    const snapshot = msgs[0]!;
    if (snapshot.type !== "snapshot") throw new Error("expected snapshot");
    expect(snapshot.status.format_mismatch).toBe(true);
    expect(snapshot.status.recorder?.message).toBe("recording stopped: low disk");
    expect(snapshot.status.warnings.map((w) => w.code)).toEqual(["format_mismatch", "recorder_stopped"]);
  });

  test("query string parsing", () => {
    const o = mockOptionsFromQuery(new URLSearchParams("outline=late&mismatch=1&recorder=low&offline=0&seed=3"));
    expect(o).toMatchObject({ outlineLate: true, formatMismatch: true, recorder: "low", offlineRig: false, seed: 3 });
    expect(mockOptionsFromQuery(new URLSearchParams("recorder=bogus")).recorder).toBe("off");
  });
});
