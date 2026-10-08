import type { TrackOutline } from "../schema";

export type Display = TrackOutline["display"];
export const IDENTITY_DISPLAY: Display = { flip_x: false, flip_z: false, rotate_deg: 0 };

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

/** World (x, z) -> map plane (right, down) using the outline's display transform (schema: TrackOutline.display). */
export function toMapPlane(x: number, z: number, display: Display): [number, number] {
  const px = display.flip_x ? -x : x;
  const py = display.flip_z ? -z : z;
  if (!display.rotate_deg) return [px, py];
  const a = (display.rotate_deg * Math.PI) / 180;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return [px * c - py * s, px * s + py * c];
}

export function emptyBounds(): Bounds {
  return { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
}

export function extend(b: Bounds, x: number, y: number): Bounds {
  if (x < b.minX) b.minX = x;
  if (x > b.maxX) b.maxX = x;
  if (y < b.minY) b.minY = y;
  if (y > b.maxY) b.maxY = y;
  return b;
}

export function isEmpty(b: Bounds): boolean {
  return !(b.maxX >= b.minX && b.maxY >= b.minY);
}

export interface Fit {
  scale: number;
  offsetX: number;
  offsetY: number;
}

/** Uniform scale + centring so the bounds fill width x height minus padding on every side. */
export function fitBounds(b: Bounds, width: number, height: number, padding: number): Fit {
  const w = Math.max(b.maxX - b.minX, 1);
  const h = Math.max(b.maxY - b.minY, 1);
  const availW = Math.max(width - 2 * padding, 1);
  const availH = Math.max(height - 2 * padding, 1);
  const scale = Math.min(availW / w, availH / h);
  return {
    scale,
    offsetX: (width - w * scale) / 2 - b.minX * scale,
    offsetY: (height - h * scale) / 2 - b.minY * scale,
  };
}

export function project(fit: Fit, x: number, y: number): [number, number] {
  return [x * fit.scale + fit.offsetX, y * fit.scale + fit.offsetY];
}

/**
 * Map orientation override from the page URL, for matching the in-game minimap before the hub
 * supplies outlines: ?map=flipx,flipz,rot90 (any combination; rotN = N degrees clockwise).
 * Returns null when the parameter is absent.
 */
export function displayFromQuery(query: URLSearchParams): Display | null {
  const raw = query.get("map");
  if (raw === null) return null;
  const display: Display = { flip_x: false, flip_z: false, rotate_deg: 0 };
  for (const token of raw.toLowerCase().split(/[,\s]+/).filter(Boolean)) {
    if (token === "flipx") display.flip_x = true;
    else if (token === "flipz") display.flip_z = true;
    else {
      const m = /^rot(-?\d+(?:\.\d+)?)$/.exec(token);
      if (m) display.rotate_deg = Number(m[1]);
    }
  }
  return display;
}

/** Short text for the override in effect, e.g. "flip z, rotated 90°". */
export function describeDisplay(d: Display): string {
  const parts = [];
  if (d.flip_x) parts.push("flip x");
  if (d.flip_z) parts.push("flip z");
  if (d.rotate_deg) parts.push(`rotated ${d.rotate_deg}°`);
  return parts.length ? parts.join(", ") : "no flip or rotation";
}
