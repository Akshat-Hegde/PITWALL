import { useEffect, useRef } from "react";
import {
  IDENTITY_DISPLAY,
  describeDisplay,
  emptyBounds,
  extend,
  fitBounds,
  isEmpty,
  project,
  toMapPlane,
  type Bounds,
  type Display,
} from "../map/geometry";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";

interface Props {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  /** From ?map=...: overrides the outline's display transform (orientation check). */
  displayOverride: Display | null;
}

const TRAIL_MS = 6000;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Canvas map: track outline, fading trails and interpolated rig dots, redrawn every animation frame. */
export function TrackMap({ store, state, trackKey, displayOverride }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Latest React state for the draw loop, without restarting it on every frame message.
  const stateRef = useRef(state);
  stateRef.current = state;
  const trackKeyRef = useRef(trackKey);
  trackKeyRef.current = trackKey;
  const overrideRef = useRef(displayOverride);
  overrideRef.current = displayOverride;
  // Without an outline the map fits everything driven so far; the bounds only ever grow.
  const seenBounds = useRef<Bounds>(emptyBounds());
  const seenTrackKey = useRef<string | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let width = 0;
    let height = 0;
    let colours = { track: "", trackEdge: "", line: "", muted: "", bg: "", path: "" };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      colours = {
        track: cssVar("--map-track"),
        trackEdge: cssVar("--map-track-edge"),
        line: cssVar("--text"),
        muted: cssVar("--text-muted"),
        bg: cssVar("--surface-0"),
        path: cssVar("--map-path"),
      };
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    resize();

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const s = stateRef.current;
      const key = trackKeyRef.current;
      if (key !== seenTrackKey.current) {
        seenTrackKey.current = key;
        seenBounds.current = emptyBounds();
      }
      const outline = key ? s.outlines[key] : undefined;
      const display: Display = overrideRef.current ?? outline?.display ?? IDENTITY_DISPLAY;
      const now = performance.now();
      const renderAt = now - 1000 / s.frameHz; // one frame behind, so there is always a sample to lerp to

      // Bounds: the outline if we have one, else everything seen on this track so far.
      let bounds: Bounds;
      if (outline) {
        bounds = emptyBounds();
        for (const [x, z] of outline.points) {
          const [px, py] = toMapPlane(x, z, display);
          extend(bounds, px, py);
        }
      } else {
        for (const segment of key ? store.paths.segments(key) : []) {
          for (const [x, z] of segment) {
            const [px, py] = toMapPlane(x, z, display);
            extend(seenBounds.current, px, py);
          }
        }
        for (const rigId of store.trails.rigIds()) {
          for (const p of store.trails.get(rigId)) {
            const [px, py] = toMapPlane(p.x, p.z, display);
            extend(seenBounds.current, px, py);
          }
        }
        bounds = seenBounds.current;
      }

      ctx.clearRect(0, 0, width, height);
      if (isEmpty(bounds)) return;
      const minSide = Math.min(width, height);
      const fit = fitBounds(bounds, width, height, minSide * 0.08);
      const toScreen = (x: number, z: number) => {
        const [px, py] = toMapPlane(x, z, display);
        return project(fit, px, py);
      };

      if (outline && outline.points.length > 2) {
        const path = new Path2D();
        outline.points.forEach(([x, z], i) => {
          const [sx, sy] = toScreen(x, z);
          if (i === 0) path.moveTo(sx, sy);
          else path.lineTo(sx, sy);
        });
        path.closePath();
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.strokeStyle = colours.trackEdge;
        ctx.lineWidth = minSide * 0.034;
        ctx.stroke(path);
        ctx.strokeStyle = colours.track;
        ctx.lineWidth = minSide * 0.026;
        ctx.stroke(path);
        drawStartLine(ctx, outline.points, toScreen, minSide, colours.line, colours.bg);
        if (outline.sector_starts) {
          for (const index of outline.sector_starts.slice(1)) {
            const p = outline.points[index];
            if (!p) continue;
            const [sx, sy] = toScreen(p[0], p[1]);
            ctx.fillStyle = colours.muted;
            ctx.beginPath();
            ctx.arc(sx, sy, minSide * 0.006, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }

      // No outline yet: the path driven so far, faintly, so the track shape shows.
      if (!outline && key) {
        ctx.strokeStyle = colours.path;
        ctx.lineWidth = minSide * 0.012;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        for (const segment of store.paths.segments(key)) {
          ctx.beginPath();
          segment.forEach(([x, z], i) => {
            const [sx, sy] = toScreen(x, z);
            if (i === 0) ctx.moveTo(sx, sy);
            else ctx.lineTo(sx, sy);
          });
          ctx.stroke();
        }
      }

      // Trails, then dots on top.
      const rigs = s.rigs;
      for (const rig of rigs) {
        const frame = s.frames[rig.rig_id];
        if (!frame || frame.session.track_key !== key) continue;
        const trail = store.trails.get(rig.rig_id);
        ctx.lineCap = "round";
        ctx.lineWidth = minSide * 0.007;
        for (let i = 1; i < trail.length; i++) {
          const a = trail[i - 1]!;
          const b = trail[i]!;
          const age = now - b.t;
          if (age > TRAIL_MS) continue;
          if (Math.hypot(b.x - a.x, b.z - a.z) > 200) continue; // don't draw across a reset or flashback
          const [ax, ay] = toScreen(a.x, a.z);
          const [bx, by] = toScreen(b.x, b.z);
          ctx.globalAlpha = 0.85 * (1 - age / TRAIL_MS);
          ctx.strokeStyle = rig.colour;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(bx, by);
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      rigs.forEach((rig, index) => {
        const frame = s.frames[rig.rig_id];
        if (!frame || frame.state !== "driving" || frame.session.track_key !== key) return;
        const pos = store.trails.positionAt(rig.rig_id, renderAt);
        if (!pos) return;
        const [sx, sy] = toScreen(pos.x, pos.z);
        const r = minSide * 0.022;
        ctx.save();
        ctx.shadowColor = rig.colour;
        ctx.shadowBlur = r * 1.6;
        ctx.fillStyle = rig.colour;
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        ctx.lineWidth = r * 0.18;
        ctx.strokeStyle = colours.bg;
        ctx.stroke();
        ctx.fillStyle = colours.bg;
        ctx.font = `700 ${Math.round(r * 1.25)}px "Barlow Condensed", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(index + 1), sx, sy + r * 0.06);
      });
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [store]);

  const hasOutline = trackKey ? Boolean(state.outlines[trackKey]) : false;
  const anyDriving = Object.values(state.frames).some((f) => f.state === "driving");
  return (
    <div className="track-map">
      <canvas ref={canvasRef} className="track-map__canvas" aria-label="Track map with live car positions" />
      {!anyDriving && <p className="track-map__note">Cars appear here when a rig is on track.</p>}
      {anyDriving && !hasOutline && (
        <p className="track-map__note track-map__note--corner">Track outline appears after the first clean lap.</p>
      )}
      {displayOverride && (
        <p className="track-map__note track-map__note--top">Map orientation: {describeDisplay(displayOverride)}</p>
      )}
    </div>
  );
}

function drawStartLine(
  ctx: CanvasRenderingContext2D,
  points: [number, number][],
  toScreen: (x: number, z: number) => [number, number],
  minSide: number,
  light: string,
  dark: string,
) {
  const a = points[0];
  const b = points[1];
  if (!a || !b) return;
  const [ax, ay] = toScreen(a[0], a[1]);
  const [bx, by] = toScreen(b[0], b[1]);
  const len = Math.hypot(bx - ax, by - ay) || 1;
  // Perpendicular to the driving direction, chequered in 4 blocks.
  const nx = -(by - ay) / len;
  const ny = (bx - ax) / len;
  const half = minSide * 0.022;
  const blocks = 4;
  ctx.lineWidth = minSide * 0.008;
  ctx.lineCap = "butt";
  for (let i = 0; i < blocks; i++) {
    const t0 = -half + (2 * half * i) / blocks;
    const t1 = -half + (2 * half * (i + 1)) / blocks;
    ctx.strokeStyle = i % 2 === 0 ? light : dark;
    ctx.beginPath();
    ctx.moveTo(ax + nx * t0, ay + ny * t0);
    ctx.lineTo(ax + nx * t1, ay + ny * t1);
    ctx.stroke();
  }
}
