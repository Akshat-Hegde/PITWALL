const MINUS = "−"; // true minus sign: same width as "+", reads better on a TV

/** 88123 -> "1:28.123"; 9123 -> "9.123". */
export function formatLapTime(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "–:––.–––";
  const total = Math.round(ms);
  const minutes = Math.floor(total / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  const millis = total % 1000;
  const frac = `${String(seconds).padStart(minutes > 0 ? 2 : 1, "0")}.${String(millis).padStart(3, "0")}`;
  return minutes > 0 ? `${minutes}:${frac}` : frac;
}

/** Sector/short times: 28011 -> "28.011". Falls back to lap format above a minute. */
export function formatSector(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "––.–––";
  return formatLapTime(ms);
}

/** Signed gap: 180 -> "+0.180", -412 -> "−0.412", 0 -> "0.000". */
export function formatDelta(ms: number | null | undefined, decimals = 3): string {
  if (ms == null || !Number.isFinite(ms)) return "–";
  const abs = Math.abs(ms) / 1000;
  const text = abs >= 60 ? formatLapTime(Math.abs(ms)) : abs.toFixed(decimals);
  if (ms === 0) return text;
  return (ms > 0 ? "+" : MINUS) + text;
}

export function formatGear(gear: number | null | undefined): string {
  if (gear == null) return "–";
  if (gear < 0) return "R";
  if (gear === 0) return "N";
  return String(gear);
}

export function formatSpeed(kph: number | null | undefined): string {
  return kph == null ? "–" : String(Math.round(kph));
}
