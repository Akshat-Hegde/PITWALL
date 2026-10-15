// The TV reloads itself when the hub is updated (its app version changes) or speaks a schema this dashboard
// can't read: nobody has to walk up to the TV PC with a keyboard. At most once per RELOAD_MIN_GAP_MS, so a hub
// that keeps disagreeing can't put the TV in a reload loop; the time of the last reload lives in sessionStorage
// because the page itself is gone after a reload.

export const RELOAD_MIN_GAP_MS = 60_000;
const RELOAD_KEY = "pitwall-tv-reload-at";

export interface ReloadDeps {
  storage: Pick<Storage, "getItem" | "setItem"> | null;
  reload: () => void;
  now: () => number;
  setTimer: (fn: () => void, ms: number) => unknown;
}

function defaultDeps(): ReloadDeps {
  let storage: ReloadDeps["storage"] = null;
  try {
    storage = window.sessionStorage;
  } catch {
    // storage blocked: see below
  }
  return {
    storage,
    reload: () => location.reload(),
    now: () => Date.now(),
    setTimer: (fn, ms) => setTimeout(fn, ms),
  };
}

let pending = false;

/**
 * Reload the page now if the last self-reload was over a minute ago, else once that minute is up.
 * Returns "now", "later" (scheduled) or "never" (no storage to remember reloads in: reloading could loop).
 */
export function requestReload(deps: ReloadDeps = defaultDeps()): "now" | "later" | "never" {
  if (pending) return "later";
  try {
    if (!deps.storage) return "never";
    const last = Number(deps.storage.getItem(RELOAD_KEY) ?? 0) || 0;
    const now = deps.now();
    const wait = last + RELOAD_MIN_GAP_MS - now;
    if (wait > 0 && last <= now) {
      pending = true;
      deps.setTimer(() => {
        pending = false;
        requestReload(deps);
      }, wait);
      return "later";
    }
    deps.storage.setItem(RELOAD_KEY, String(now));
    deps.reload();
    return "now";
  } catch {
    return "never";
  }
}

/** For tests. */
export function resetReloadState(): void {
  pending = false;
}
