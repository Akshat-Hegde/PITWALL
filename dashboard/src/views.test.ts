import { describe, expect, test } from "vitest";
import { ATTRACT_BOARD_MS, ATTRACT_RACE_MS, IDLE_AFTER_MS, chooseView, viewModeFromQuery } from "./views";

describe("TV views", () => {
  test("URL picks the mode; anything else is auto", () => {
    const mode = (q: string) => viewModeFromQuery(new URLSearchParams(q));
    expect([mode("view=race"), mode("view=board"), mode("view=x"), mode("")]).toEqual(["race", "board", "auto", "auto"]);
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
});
