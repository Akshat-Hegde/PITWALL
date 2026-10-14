// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { RacePodiumMoment } from "../schema";
import { initialState, type DashboardState } from "../state/reducer";
import { MOMENT_MS } from "./Moments";
import { RACE_PODIUM_PHASE_MS, RacePodium } from "./RacePodium";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PASSWORD = "racefast1";
const WIFI = { ssid: "Cafe Guest", qr: `WIFI:T:WPA;S:Cafe Guest;P:${PASSWORD};;` };
const NAMES = ["Maya R", "Kofi A", "Lena K", "Tom B", "Ines P"];

function moment(n: number, wifi: RacePodiumMoment["wifi"] = WIFI): RacePodiumMoment {
  return {
    kind: "race_podium", at: 1, track_key: "F1:7", track_name: "Silverstone", session_type: "Race",
    drivers: Array.from({ length: n }, (_, i) => ({
      rank: i + 1, position: i * 2 + 3, driver: NAMES[i % NAMES.length]!, rig_id: `rig-${i}`,
      grid_position: 10 - i, laps: 5, best_lap_ms: 87_000 + i * 100, total_time_s: 440 + i * 3.7,
      status: "finished", card_url: `http://hub/card/tok${i}`, card_token: `tok${i}`,
    })),
    wifi,
  };
}

let el: HTMLDivElement;
let root: Root;
const state: DashboardState = { ...initialState("hub"), link: "live" };

beforeEach(() => {
  vi.useFakeTimers();
  el = document.createElement("div");
  root = createRoot(el);
});

afterEach(() => {
  act(() => root.unmount());
  vi.useRealTimers();
});

test("the race podium runs 40 s: 15 s podium, then Grab your card", () => {
  expect(MOMENT_MS.race_podium).toBe(40_000);
  expect(RACE_PODIUM_PHASE_MS).toBe(15_000);
});

test("phase 1: the top three cafe drivers, each with a QR to their card beside the name", () => {
  act(() => root.render(<RacePodium m={moment(5)} state={state} />));
  const steps = el.querySelectorAll(".racepodium__step");
  expect(steps).toHaveLength(3);
  const qrs = el.querySelectorAll(".racepodium__step .qr");
  expect(qrs).toHaveLength(3);
  for (const [i, name] of NAMES.slice(0, 3).entries()) {
    const step = el.querySelector(`.racepodium__step--r${i + 1}`)!;
    expect(step.textContent).toContain(name);
    expect(step.querySelector(".qr")?.getAttribute("aria-label")).toContain(`tok${i}`);
  }
  // The real race position, not the cafe rank.
  expect(el.querySelector(".racepodium__step--r1")?.textContent).toContain("P3");
  expect(el.querySelector(".racepodium__grid")).toBeNull();
});

test("phase 2: a grid of every finisher with a QR, plus the Wi-Fi tile; never the password", () => {
  act(() => root.render(<RacePodium m={moment(5)} state={state} />));
  act(() => { vi.advanceTimersByTime(RACE_PODIUM_PHASE_MS); });
  expect(el.querySelector(".racepodium__step")).toBeNull();
  expect(el.textContent).toContain("Grab your card");
  const tiles = el.querySelectorAll(".racepodium__tile--driver");
  expect(tiles).toHaveLength(5);
  expect(tiles[3]!.textContent).toContain("Tom B");
  expect(tiles[3]!.textContent).toContain("P9");
  expect(tiles[3]!.querySelector(".qr")).not.toBeNull();
  const wifi = el.querySelector(".racepodium__tile--wifi")!;
  expect(wifi.textContent).toContain("Join our Wi-Fi");
  expect(wifi.textContent).toContain("Cafe Guest");
  expect(wifi.querySelector(".qr")).not.toBeNull();
  expect(el.innerHTML).not.toContain(PASSWORD);
});

test("phase 2 shows at most 10 finishers, and no Wi-Fi tile without a guest network", () => {
  act(() => root.render(<RacePodium m={moment(12, null)} state={state} />));
  act(() => { vi.advanceTimersByTime(RACE_PODIUM_PHASE_MS); });
  expect(el.querySelectorAll(".racepodium__tile--driver")).toHaveLength(10);
  expect(el.querySelector(".racepodium__tile--wifi")).toBeNull();
});

test("the Wi-Fi from the cafe settings is used when the moment has none", () => {
  const withWifi = { ...state, cafe: { ...state.cafe, wifi: WIFI } };
  act(() => root.render(<RacePodium m={moment(2, null)} state={withWifi} />));
  // Two drivers: a podium of two.
  expect(el.querySelectorAll(".racepodium__step")).toHaveLength(2);
  act(() => { vi.advanceTimersByTime(RACE_PODIUM_PHASE_MS); });
  expect(el.querySelector(".racepodium__tile--wifi")?.textContent).toContain("Cafe Guest");
  expect(el.innerHTML).not.toContain(PASSWORD);
});
