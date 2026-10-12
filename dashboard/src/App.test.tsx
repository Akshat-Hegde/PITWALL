// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { App, WIPE_MS } from "./App";
import { formatSpeed } from "./format";
import { DEFAULT_MOCK_OPTIONS, MockHub } from "./mock/sim";
import type { HubMessage } from "./schema";
import { DashboardStore } from "./state/store";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

class NoResize {
  observe() {}
  unobserve() {}
  disconnect() {}
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("ResizeObserver", NoResize);
  HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function fedStore(seconds = 4): { store: DashboardStore; hub: MockHub; tick: () => void } {
  let clock = 1_791_300_000_000;
  const hub = new MockHub({ ...DEFAULT_MOCK_OPTIONS, rigs: 2 }, () => clock);
  const store = new DashboardStore("mock");
  store.dispatch(hub.snapshot());
  const tick = () => {
    clock += 67;
    for (const msg of hub.step(1000 / 15)) store.dispatch(msg as HubMessage);
  };
  for (let i = 0; i < seconds * 15; i++) tick();
  return { store, hub, tick };
}

function press(key: string) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key }));
  });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("TV view transitions", () => {
  test("only one view is mounted after a transition, and the wipe goes away", () => {
    const { store } = fedStore();
    act(() => root.render(<App store={store} />));
    expect(host.querySelectorAll(".app__view")).toHaveLength(1);
    expect(host.querySelector(".wipe")).toBeNull(); // no wipe on first load

    for (const key of ["2", "1", "2", "1", "3", "1"]) {
      press(key);
      expect(host.querySelectorAll(".app__view")).toHaveLength(1);
      advance(WIPE_MS + 50);
      expect(host.querySelectorAll(".app__view")).toHaveLength(1);
      expect(host.querySelectorAll(".wipe")).toHaveLength(0);
    }
    expect(host.querySelector(".app__view > main")?.className).toContain("live");
  });

  test("after switching views, every speed shown is the rig's live speed", () => {
    const { store, tick } = fedStore();
    act(() => root.render(<App store={store} />));
    press("2");
    advance(WIPE_MS + 50);
    press("1");
    advance(WIPE_MS + 50);
    act(() => {
      for (let i = 0; i < 30; i++) tick(); // the cars keep moving
    });
    const frames = Object.values(store.getState().frames).filter((f) => f.state === "driving");
    expect(frames.length).toBeGreaterThan(0);
    // LIVE: the focus card shows the focus driver's live speed.
    const card = host.querySelector(".pw-card__driver")?.textContent;
    const focus = frames.find((f) => (f.driver ?? "").toUpperCase() === card);
    expect(focus).toBeDefined();
    expect(host.querySelector(".pw-speed__v")?.textContent).toBe(String(Math.round(focus!.speed_kph ?? 0)));
    // MULTIVIEW: every tile shows its rig's live speed.
    press("2");
    advance(WIPE_MS + 50);
    const shown = [...host.querySelectorAll(".spg__speed")].map((e) => e.textContent);
    expect(shown.sort()).toEqual(frames.map((f) => formatSpeed(f.speed_kph)).sort());
  });
});

describe("TV never shows technical diagnostics", () => {
  test("no IP addresses or warnings, even with a port conflict and a silent rig", () => {
    const { store } = fedStore();
    store.dispatch({
      v: 1, type: "status", seq: 0, ts: 0,
      status: {
        format_mismatch: false, formats: {}, recorder: null,
        warnings: [{ code: "port_shadowed", rig_id: null, message: "simpro3.exe also listens on 127.0.0.1:20777" }],
      },
    } as unknown as HubMessage);
    act(() => root.render(<App store={store} />));
    // Text per element, so neighbouring numbers (four tyre pressures) don't run together.
    const text = [...host.querySelectorAll("*")].filter((e) => e.children.length === 0).map((e) => e.textContent).join(" | ");
    expect(text.match(/\b\d{1,3}(\.\d{1,3}){3}\b/)?.[0] ?? null).toBeNull();
    expect(text).not.toContain("simpro");
    expect(host.querySelector(".tabs")).toBeNull(); // view switching is on /staff and the keys, not the TV
  });
});

describe("TV pages and switching", () => {
  test("a key press on the TV PC picks the page, and it survives a reload", () => {
    localStorage.clear();
    const { store } = fedStore();
    act(() => root.render(<App store={store} />));
    expect(host.querySelector(".app__view > main")?.className).toContain("live");
    press("2");
    expect(host.querySelector(".app__view > main")?.className).toContain("multi");
    act(() => root.unmount());
    root = createRoot(host);
    act(() => root.render(<App store={store} />));
    expect(host.querySelector(".app__view > main")?.className).toContain("multi");
    localStorage.clear();
  });

  test("a newer staff choice from the hub switches the page", () => {
    localStorage.clear();
    const { store } = fedStore();
    act(() => root.render(<App store={store} />));
    act(() => store.dispatch({ v: 1, type: "tv", seq: 0, ts: 0,
      tv: { page: "multi", pinned_rig: null, overlay: null, updated_at: Date.now() } } as HubMessage));
    expect(host.querySelector(".app__view > main")?.className).toContain("multi");
  });

  test("a moment is an overlay: the page underneath stays", () => {
    localStorage.clear();
    const { store, hub } = fedStore();
    act(() => root.render(<App store={store} />));
    const rig = store.getState().rigs[0]!;
    act(() => store.dispatch({ v: 1, type: "moment", seq: 0, ts: 0, moment: {
      kind: "now_driving", at: Date.now(), rig_id: rig.rig_id, rig_name: rig.name, driver: "Maya", track_name: null,
      record: null, personal_best: null } } as unknown as HubMessage));
    void hub;
    expect(host.querySelectorAll(".app__view")).toHaveLength(1);
    expect(host.querySelector(".app__view > main")?.className).toContain("live");
  });
});
