/** Saving the story card on a guest's phone. */

/** iPhone, iPad and iPod, including iPadOS, which reports a desktop Mac user agent but has a touch screen.
 *  Safari there ignores a download link for an image, so the card is shown to press and hold instead. */
export function isIOS(userAgent: string, platform = "", maxTouchPoints = 0): boolean {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return true;
  return (platform === "MacIntel" || /Macintosh/i.test(userAgent)) && maxTouchPoints > 1;
}

export function isThisIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  return isIOS(navigator.userAgent ?? "", navigator.platform ?? "", navigator.maxTouchPoints ?? 0);
}

/** "lap-card-Alex.png"; a name with no Latin letters or digits (e.g. "अर्जुन") gives "lap-card.png",
 *  never "lap-card-_.png". */
export function cardFileName(kind: "race" | "session" | string | undefined, driver: string | null | undefined): string {
  const prefix = kind === "race" ? "race-card" : "lap-card";
  const slug = (driver ?? "").replace(/[^\w-]+/g, "_").replace(/^[_-]+|[_-]+$/g, "");
  return /[A-Za-z0-9]/.test(slug) ? `${prefix}-${slug}.png` : `${prefix}.png`;
}
