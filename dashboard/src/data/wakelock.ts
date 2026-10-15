// Keeps the TV screen on while the dashboard is showing, where the browser allows it (secure contexts such as
// localhost). The browser releases the lock whenever the tab is hidden, so it is asked for again each time the
// page becomes visible. Any failure is ignored: the TV PC's power settings are the fallback.

interface WakeLockLike {
  request(type: "screen"): Promise<unknown>;
}

export function keepScreenAwake(nav: { wakeLock?: WakeLockLike } = navigator as never,
                                doc: Pick<Document, "visibilityState" | "addEventListener"> = document): void {
  const wakeLock = nav.wakeLock;
  if (!wakeLock || typeof wakeLock.request !== "function") return;
  const request = () => {
    try {
      wakeLock.request("screen").catch(() => undefined);
    } catch {
      // not allowed here
    }
  };
  request();
  doc.addEventListener("visibilitychange", () => {
    if (doc.visibilityState === "visible") request();
  });
}
