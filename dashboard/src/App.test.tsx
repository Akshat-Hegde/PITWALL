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

    for (const key of ["4", "1", "4", "1", "2", "1"]) {
      press(key);
      expect(host.querySelectorAll(".app__view")).toHaveLength(1);
      advance(WIPE_MS + 50);
      expect(host.querySelectorAll(".app__view")).toHaveLength(1);
      expect(host.querySelectorAll(".wipe")).toHaveLength(0);
    }
    expect(host.querySelector(".app__view > main")?.className).toContain("race");
  });

  test("after switching views, every speed shown is the rig's live speed", () => {
    const { store, tick } = fedStore();
    act(() => root.render(<App store={store} />));
    press("4");
    advance(WIPE_MS + 50);
    press("1");
    advance(WIPE_MS + 50);
    act(() => {
      for (let i = 0; i < 30; i++) tick(); // the cars keep moving
    });
    const frames = Object.values(store.getState().frames).filter((f) => f.state === "driving");
    expect(frames.length).toBeGreaterThan(0);
    const shown = [...host.querySelectorAll(".speed__value")].map((e) => e.textContent);
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
    const text = host.textContent ?? "";
    expect(text).not.toMatch(/\b\d{1,3}(\.\d{1,3}){3}\b/);
    expect(text).not.toContain("simpro");
    expect(host.querySelector(".tabs")).toBeNull(); // view switching is on /staff and the keys, not the TV
  });
});
