import { describe, expect, test } from "vitest";
import {
  ATTRACT_BOARD_MS, ATTRACT_RACE_MS, IDLE_AFTER_MS, LIVE_ANALYSIS_MS, LIVE_RACE_MS, chooseView, viewModeFromQuery,
} from "./views";

describe("TV views", () => {
  test("URL picks the mode; anything else is auto", () => {
    const mode = (q: string) => viewModeFromQuery(new URLSearchParams(q));
    expect([mode("view=race"), mode("view=board"), mode("view=x"), mode("")]).toEqual(["race", "board", "auto", "auto"]);
    expect([mode("view=analysis"), mode("view=onboard")]).toEqual(["analysis", "onboard"]);
  });

  test("auto: race while someone drives or just stopped", () => {
    expect(chooseView("auto", null)).toEqual({ view: "race", attract: false });
    expect(chooseView("auto", IDLE_AFTER_MS - 1)).toEqual({ view: "race", attract: false });
  });

  test("auto: attract mode alternates leaderboard and race", () => {
    expect(chooseView("auto", IDLE_AFTER_MS)).toEqual({ view: "board", attract: true });
    expect(chooseView("auto", IDLE_AFTER_MS + ATTRACT_BOARD_MS)).toEqual({ view: "race", attract: true });
    const cycle = ATTRACT_BOARD_MS + ATTRACT_RACE_MS;
    expect(chooseView("auto", IDLE_AFTER_MS + cycle + 1).view).toBe("board");
  });

  test("a fixed view ignores driving and idling", () => {
    expect(chooseView("board", null)).toEqual({ view: "board", attract: false });
    expect(chooseView("race", 10 * 60_000)).toEqual({ view: "race", attract: false });
  });

  test("while driving: race, then head to head and onboard when they have something to show", () => {
    const both = { analysis: true, onboard: true };
    const at = (t: number, available = both) => chooseView("auto", null, t, available).view;
    expect(at(0)).toBe("race");
    expect(at(LIVE_RACE_MS)).toBe("analysis");
    expect(at(LIVE_RACE_MS + LIVE_ANALYSIS_MS)).toBe("onboard");
    expect(at(LIVE_RACE_MS, { analysis: false, onboard: true })).toBe("onboard");
    expect(at(LIVE_RACE_MS, { analysis: false, onboard: false })).toBe("race");
  });

  test("attract mode adds head to head when there is one", () => {
    const idle = IDLE_AFTER_MS + ATTRACT_BOARD_MS + ATTRACT_RACE_MS;
    expect(chooseView("auto", idle, 0, { analysis: true, onboard: false }).view).toBe("analysis");
    expect(chooseView("auto", idle, 0, { analysis: false, onboard: false }).view).toBe("board");
  });
});
