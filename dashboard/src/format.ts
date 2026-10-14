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

/** 1 -> "1st", 2 -> "2nd", 11 -> "11th", 23 -> "23rd". */
export function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

/** Race time in seconds: 462.315 -> "7:42.315"; 3723.4 -> "1:02:03.400"; null -> "–". */
export function formatRaceTime(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s <= 0) return "–";
  const ms = Math.round(s * 1000);
  const hours = Math.floor(ms / 3_600_000);
  const rest = formatLapTime(ms % 3_600_000);
  if (!hours) return rest;
  const [m, sec] = rest.includes(":") ? rest.split(":") : ["0", rest.padStart(6, "0")];
  return `${hours}:${m!.padStart(2, "0")}:${sec}`;
}

const RACE_STATUS: Record<string, string> = { dnf: "DNF", dsq: "DSQ", not_classified: "NC", retired: "RET" };

/** The race result as shown: "P4" for a finisher, else DNF / DSQ / NC / RET. */
export function raceResult(status: string, position: number): string {
  return RACE_STATUS[status] ?? `P${position}`;
}
