import { afterEach, describe, expect, test } from "vitest";
import { challengeWhen } from "../components/Competition";
import { MockHub } from "../mock/sim";
import type { Challenge } from "../schema";
import { HubClock, hubClock, hubNow } from "./hubclock";
import { DashboardStore } from "./store";

describe("hub time", () => {
  afterEach(() => hubClock.reset());

  test("offset from the message's ts: the TV clock may be minutes off", () => {
    const clock = new HubClock();
    expect(clock.now(5_000)).toBe(5_000);
    clock.observe(1_000_000, 1_300_000); // TV PC clock 5 minutes fast
    expect(clock.offset).toBe(-300_000);
    expect(clock.now(1_310_000)).toBe(1_010_000);
  });

  test("bad timestamps are ignored", () => {
    const clock = new HubClock();
    clock.observe(1_000, 2_000);
    for (const ts of [undefined, null, "1", NaN, 0, -5]) clock.observe(ts, 9_999_999);
    expect(clock.offset).toBe(-1_000);
  });

  test("the store feeds the dashboard's clock from every message", () => {
    const store = new DashboardStore("hub");
    const snap = new MockHub().snapshot();
    store.dispatch({ ...snap, ts: Date.now() + 3_600_000 });
    expect(Math.abs(hubNow() - Date.now() - 3_600_000)).toBeLessThan(1_000);
  });

  test("the challenge countdown uses hub time", () => {
    const now = Date.now();
    const c = { state: "running", starts_at: now - 1, ends_at: now + 3 * 24 * 3600_000 } as Challenge;
    expect(challengeWhen(c)).toBe("3 days left");
    hubClock.observe(now + 24 * 3600_000, now); // the hub is a day ahead of this PC
    expect(challengeWhen(c)).toBe("2 days left");
  });
});
