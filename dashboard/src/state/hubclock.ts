// Hub time on the TV. Every hub message carries `ts` (the hub's wall clock, Unix ms). The TV PC's own clock may
// be minutes off, so every comparison with a hub timestamp (card QR timeout, challenge countdown, the session
// story window, key press vs staff choice) uses hub time: the TV clock plus the offset seen on the last message.

export class HubClock {
  private offsetMs = 0;

  /** A message stamped `ts` (hub ms) arrived at `localMs` (this PC's clock). */
  observe(ts: unknown, localMs = Date.now()): void {
    if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return;
    this.offsetMs = ts - localMs;
  }

  /** Hub time minus the TV's clock, ms (0 until a message has arrived). */
  get offset(): number {
    return this.offsetMs;
  }

  /** The hub's current time, Unix ms. */
  now(localMs = Date.now()): number {
    return localMs + this.offsetMs;
  }

  reset(): void {
    this.offsetMs = 0;
  }
}

/** The one clock the dashboard uses (fed by DashboardStore.dispatch). */
export const hubClock = new HubClock();

/** The hub's current time, Unix ms. Use this instead of Date.now() whenever the result meets a hub timestamp. */
export const hubNow = (): number => hubClock.now();
