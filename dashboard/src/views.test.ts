import { describe, expect, test } from "vitest";
import type { TvSetting } from "./schema";
import { ATTRACT_HERO_MS, IDLE_AFTER_MS, chooseView, currentPage, viewModeFromQuery } from "./views";

const TV: TvSetting = { page: "live", pinned_rig: null, overlay: null, updated_at: 1000 };
const ALL = { analysis: true, attract: true, teams: true };

describe("TV pages", () => {
  test("URL fixes the view; anything else is auto", () => {
    const mode = (q: string) => viewModeFromQuery(new URLSearchParams(q));
    expect([mode("view=live"), mode("view=multi"), mode("view=race"), mode("")]).toEqual(["live", "multi", "auto", "auto"]);
  });

  test("while anyone drives: the chosen page, never rotating", () => {
    for (const page of ["live", "multi"] as const) {
      expect(chooseView("auto", page, null, null, ALL)).toEqual({ view: page, attract: false });
    }
  });

  test("attract mode only after 60 s with nobody driving, and back to the page when someone drives", () => {
    expect(IDLE_AFTER_MS).toBe(60_000);
    expect(chooseView("auto", "multi", null, IDLE_AFTER_MS - 1, ALL).view).toBe("multi");
    expect(chooseView("auto", "multi", null, IDLE_AFTER_MS, ALL)).toEqual({ view: "attract", attract: true });
    expect(chooseView("auto", "multi", null, IDLE_AFTER_MS + ATTRACT_HERO_MS, ALL).view).toBe("board");
    expect(chooseView("auto", "multi", null, null, ALL).view).toBe("multi");
    expect(chooseView("auto", "live", null, IDLE_AFTER_MS * 5, { analysis: false, attract: false }).view).toBe("live");
  });

  test("staff can put head to head or the teams over the page, when there is one", () => {
    expect(chooseView("auto", "live", "head_to_head", null, ALL).view).toBe("analysis");
    expect(chooseView("auto", "live", "head_to_head", null, { analysis: false }).view).toBe("live");
    expect(chooseView("auto", "live", "teams", IDLE_AFTER_MS * 2, ALL).view).toBe("teams");
  });

  test("no tournament preview: attract rotates welcome, board and teams only", () => {
    expect(viewModeFromQuery(new URLSearchParams("view=bracket"))).toBe("auto");
    const seen = new Set<string>();
    for (let t = 0; t < 200_000; t += 1_000) seen.add(chooseView("auto", "live", null, IDLE_AFTER_MS + t, ALL).view);
    expect([...seen].sort()).toEqual(["attract", "board", "teams"]);
  });

  test("the newer of the staff choice and a key press on the TV PC wins", () => {
    expect(currentPage(TV, null)).toBe("live");
    expect(currentPage(TV, { page: "multi", at: 2000 })).toBe("multi");
    expect(currentPage({ ...TV, page: "live", updated_at: 3000 }, { page: "multi", at: 2000 })).toBe("live");
  });
});
