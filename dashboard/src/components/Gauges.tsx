
// ---- Tyre temperatures -------------------------------------------------------------------------

/** Surface temperature to a band; shown as text colour (cold blue, in range white, warm amber, hot red). */
export function tyreTempBand(c: number | null): string {
  if (c == null || c <= 0) return "none";
  if (c < 70) return "cold";
  if (c < 85) return "cool";
  if (c < 105) return "ok";
  if (c < 115) return "warm";
  return "hot";
}
