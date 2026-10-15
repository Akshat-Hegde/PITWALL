import { beforeEach, describe, expect, test, vi } from "vitest";
import { RELOAD_MIN_GAP_MS, requestReload, resetReloadState, type ReloadDeps } from "./reload";
import { keepScreenAwake } from "./wakelock";

function deps(now: number, stored: Record<string, string> = {}) {
  const timers: { fn: () => void; ms: number }[] = [];
  const d: ReloadDeps & { timers: typeof timers; reloads: number; clock: number } = {
    timers,
    reloads: 0,
    clock: now,
    storage: { getItem: (k) => stored[k] ?? null, setItem: (k, v) => void (stored[k] = v) },
    reload: () => void d.reloads++,
    now: () => d.clock,
    setTimer: (fn, ms) => timers.push({ fn, ms }),
  };
  return d;
}

describe("self reload", () => {
  beforeEach(() => resetReloadState());

  test("reloads at once the first time", () => {
    const d = deps(1_000_000);
    expect(requestReload(d)).toBe("now");
    expect(d.reloads).toBe(1);
  });

  test("at most once a minute: a second request waits for the minute to pass, then reloads", () => {
    const stored: Record<string, string> = {};
    const first = deps(1_000_000, stored);
    requestReload(first);
    const d = deps(1_000_000 + 20_000, stored); // the page reloaded; 20 s later the hub disagrees again
    expect(requestReload(d)).toBe("later");
    expect(requestReload(d)).toBe("later"); // no second timer
    expect(d.reloads).toBe(0);
    expect(d.timers).toHaveLength(1);
    expect(d.timers[0]!.ms).toBe(RELOAD_MIN_GAP_MS - 20_000);
    d.clock += d.timers[0]!.ms;
    d.timers[0]!.fn();
    expect(d.reloads).toBe(1);
  });

  test("never reloads without storage (it couldn't remember, and might loop) or when storage throws", () => {
    const d = deps(1_000_000);
    expect(requestReload({ ...d, storage: null })).toBe("never");
    const throwing = { ...d, storage: { getItem: () => { throw new Error("blocked"); }, setItem: () => undefined } };
    expect(requestReload(throwing)).toBe("never");
    expect(d.reloads).toBe(0);
  });
});

describe("screen wake lock", () => {
  test("asks for a lock, and again when the page becomes visible; failures are ignored", async () => {
    const request = vi.fn().mockRejectedValue(new Error("not allowed"));
    let onVisible: (() => void) | null = null;
    const doc = { visibilityState: "visible" as DocumentVisibilityState,
      addEventListener: (_: string, fn: () => void) => void (onVisible = fn) };
    keepScreenAwake({ wakeLock: { request } }, doc as never);
    expect(request).toHaveBeenCalledWith("screen");
    onVisible!();
    expect(request).toHaveBeenCalledTimes(2);
    await Promise.resolve();
  });

  test("does nothing where the browser has no wake lock", () => {
    expect(() => keepScreenAwake({}, { visibilityState: "visible", addEventListener: () => undefined } as never))
      .not.toThrow();
  });
});
