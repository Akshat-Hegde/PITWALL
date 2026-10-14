// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import type { CardMoment } from "../schema";
import { initialState, type DashboardState } from "../state/reducer";
import { CardQr } from "./CardQr";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const card = (extra: Partial<CardMoment> = {}): CardMoment => ({
  kind: "card", at: Date.now(), rig_id: "r", driver: "Maya R", token: "t", url: "http://hub/card/t", best_ms: 87_259,
  track_name: "Silverstone", ...extra,
});

function render(state: DashboardState) {
  const el = document.createElement("div");
  const root = createRoot(el);
  act(() => root.render(<CardQr state={state} />));
  return { el, root };
}

test("the Wi-Fi QR sits beside the card QR when the cafe has a guest network; SSID only", () => {
  const wifi = { ssid: "Cafe Guest", qr: "WIFI:T:WPA;S:Cafe Guest;P:racefast1;;" };
  const base = { ...initialState("hub"), cards: [card()] };
  const { el, root } = render({ ...base, cafe: { ...base.cafe, wifi } });
  expect(el.querySelectorAll(".qr")).toHaveLength(2);
  expect(el.querySelector(".cardqr__wifi")?.textContent).toContain("Cafe Guest");
  expect(el.innerHTML).not.toContain("racefast1");
  act(() => root.render(<CardQr state={base} />));
  expect(el.querySelectorAll(".qr")).toHaveLength(1);
  expect(el.querySelector(".cardqr__wifi")).toBeNull();
  act(() => root.unmount());
});

test("a solo race card says race card and the race position", () => {
  const { el, root } = render({ ...initialState("hub"), cards: [card({ card_kind: "race", position: 4 })] });
  expect(el.textContent).toContain("Your race card");
  expect(el.textContent).toContain("P4");
  act(() => root.unmount());
});
