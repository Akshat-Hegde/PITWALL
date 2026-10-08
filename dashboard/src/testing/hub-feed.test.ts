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
    expect(driving.every((f) => f.lap === null && f.best === null)).toBe(true); // no lap tracking yet
    // Rig A just started a new session in the sample, so only Rig B has a position yet.
    expect(driving.filter((f) => f.position !== null).length).toBe(1);
  });
});
