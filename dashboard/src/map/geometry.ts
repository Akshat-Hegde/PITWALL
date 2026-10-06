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
