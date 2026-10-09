import { describe, expect, test } from "vitest";
import type { HubMessage } from "../schema";
import { applyMessage, initialState } from "../state/reducer";
import sample from "./hub-feed.sample.json";
import { validateMessage } from "./validate";

// Produced by the hub's own feed code (hub/tests/test_feed.py), so the hub and the dashboard
// are checked against the same schema validator.
const messages = sample as unknown as HubMessage[];

describe("hub feed sample", () => {
  test("every message the hub sends validates against schema v1", () => {
    const problems = messages.flatMap((m) => validateMessage(m).map((e) => `seq ${m.seq}: ${e}`));
    expect(problems).toEqual([]);
  });

  test("the dashboard state accepts it", () => {
    let state = initialState("hub");
    for (const m of messages) state = applyMessage(state, m, 0);
    expect(state.link).toBe("live");
    expect(state.rigs.length).toBe(3);
    const driving = Object.values(state.frames).filter((f) => f.state === "driving");
    expect(driving.length).toBe(2);
    // Rig A completed a lap (lap_completed, track_outline, leaderboard), then changed track.
    expect(Object.keys(state.outlines)).toEqual(["F1:7"]);
    expect(state.recentLaps.map((l) => l.lap_ms)).toEqual([88123]);
    expect(state.leaderboard?.entries.map((e) => e.driver)).toEqual(["Akshat"]);
    const rigA = state.frames["192.168.1.21"]!;
    expect(rigA.session.track_key).toBe("F1:10");
    expect(rigA.lap).toBeNull(); // new session: nothing carried over
    expect(rigA.best).toBeNull(); // no best on the new track yet
  });
});
