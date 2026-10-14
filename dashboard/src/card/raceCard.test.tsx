// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import type { RaceStoryCard } from "../schema";
import { CardPage } from "./CardPage";
import { demoRaceCard } from "./demo";
import { raceCardText } from "./drawCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom has no canvas: the drawing is skipped (raceCardText above is what the drawing shows).
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];

const race = (extra: Partial<RaceStoryCard> = {}): RaceStoryCard => ({ ...demoRaceCard(), ...extra });

test("race card text: big position, race and track, grid to finish, best lap, total time, cafe result", () => {
  const t = raceCardText(race({ position: 4, grid_position: 7, positions_gained: 3, best_lap_ms: 87_259,
    best_ms: 87_259, total_time_s: 462.315, penalties_s: 0, track_name: "Silverstone", cafe_rank: 1,
    cafe_drivers: 4, cafe: { name: "Lap Lounge", branding: {} } }));
  expect(t.big).toBe("P4");
  expect(t.title).toBe("Race · Silverstone");
  expect(t.grid).toBe("P7 → P4");
  expect(t.gained).toBe("+3 places");
  expect(t.best).toBe("1:27.259");
  expect(t.total).toBe("7:42.315");
  expect(t.penalties).toBeNull();
  expect(t.cafe).toBe("1st of 4 at Lap Lounge");
});

test("race card text: places lost, one place, penalties, no grid, not classified", () => {
  expect(raceCardText(race({ positions_gained: -2 })).gained).toBe("−2 places");
  expect(raceCardText(race({ positions_gained: 1 })).gained).toBe("+1 place");
  expect(raceCardText(race({ positions_gained: 0 })).gained).toBe("Held position");
  const t = raceCardText(race({ grid_position: null, positions_gained: null, penalties_s: 5, status: "dnf",
    total_time_s: null, best_lap_ms: null, best_ms: null, cafe_rank: 2, cafe_drivers: 2 }));
  expect(t.big).toBe("DNF");
  expect(t.grid).toBeNull();
  expect(t.gained).toBeNull();
  expect(t.penalties).toBe("+5 s penalty");
  expect(t.total).toBe("–");
  expect(t.best).toBe("–");
  expect(t.cafe).toContain("2nd of 2 at");
  expect(raceCardText(race({ cafe_rank: 1, cafe_drivers: 1, cafe: { name: "Lap Lounge", branding: {} } })).cafe)
    .toBe("Raced at Lap Lounge");
});

test("the card page saves for Instagram story, with the help line, for race and session cards", async () => {
  for (const token of ["demo-race", "demo"]) {
    const el = document.createElement("div");
    const root = createRoot(el);
    await act(async () => root.render(<CardPage token={token} />));
    const button = el.querySelector(".cardpage__btn--primary");
    expect(button?.textContent).toBe("Save for Instagram story");
    expect(el.textContent).toContain("Then post it from your gallery to your Instagram story.");
    await act(async () => root.unmount());
  }
});
