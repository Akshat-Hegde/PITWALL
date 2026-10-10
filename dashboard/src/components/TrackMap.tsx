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
import { Waiting } from "./Waiting";

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
    let colours = { track: "", trackEdge: "", line: "", muted: "", bg: "", path: "", s1: "", s2: "", s3: "",
      fontHead: "sans-serif", fontBody: "sans-serif" };

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
        s1: cssVar("--map-s1"),
        s2: cssVar("--map-s2"),
        s3: cssVar("--map-s3"),
        fontHead: cssVar("--font-head") || "sans-serif",
        fontBody: cssVar("--font-body") || "sans-serif",
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
        // Sector colours down the middle of the track, with an S1/S2/S3 label where each starts.
        const starts = outline.sector_starts ?? null;
        if (starts) {
          const n = outline.points.length;
          const sectorColours = [colours.s1, colours.s2, colours.s3];
          for (let k = 0; k < 3; k++) {
            const from = starts[k]!;
            const to = k < 2 ? starts[k + 1]! : n;
            const seg = new Path2D();
            for (let i = from; i <= to; i++) {
              const pt = outline.points[i % n]!;
              const [sx, sy] = toScreen(pt[0], pt[1]);
              if (i === from) seg.moveTo(sx, sy);
              else seg.lineTo(sx, sy);
            }
            ctx.strokeStyle = sectorColours[k]!;
            ctx.lineWidth = minSide * 0.006;
            ctx.stroke(seg);
          }
        }
        drawStartLine(ctx, outline.points, toScreen, minSide, colours.line, colours.bg);
        if (starts) {
          const fontPx = Math.round(Math.max(11, minSide * 0.02));
          ctx.font = `700 ${fontPx}px ${colours.fontBody}`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          starts.forEach((index, k) => {
            const p0 = outline.points[(index + 3) % outline.points.length];
            if (!p0) return;
            const [sx, sy] = toScreen(p0[0], p0[1]);
            const rr = fontPx * 0.95;
            ctx.fillStyle = colours.bg;
            ctx.beginPath();
            ctx.arc(sx, sy, rr, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = [colours.s1, colours.s2, colours.s3][k]!;
            ctx.lineWidth = Math.max(1.5, fontPx * 0.12);
            ctx.stroke();
            ctx.fillStyle = colours.line;
            ctx.fillText(`S${k + 1}`, sx, sy + 1);
          });
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
      const placedTags: { x: number; y: number; w: number; h: number }[] = [];
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
        ctx.font = `italic 700 ${Math.round(r * 1.15)}px ${colours.fontHead}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(index + 1), sx, sy + r * 0.06);

        // Name tag next to the dot, in the rig's colour.
        const name = frame.driver ?? rig.name;
        const fontPx = Math.round(Math.max(12, minSide * 0.024));
        ctx.font = `italic 700 ${fontPx}px ${colours.fontHead}`;
        const padX = fontPx * 0.45;
        const tagW = ctx.measureText(name).width + padX * 2;
        const tagH = fontPx * 1.35;
        let tx = sx + r * 1.35;
        if (tx + tagW > width - 4) tx = sx - r * 1.35 - tagW; // keep it on screen
        let ty = sy - r * 1.1 - tagH;
        // Cars close together: stack their tags instead of drawing them on top of each other.
        const overlaps = (y: number) =>
          placedTags.some((p) => tx < p.x + p.w && tx + tagW > p.x && y < p.y + p.h && y + tagH > p.y);
        for (let tries = 0; tries < 6 && overlaps(ty); tries++) ty -= tagH + 3;
        placedTags.push({ x: tx, y: ty, w: tagW, h: tagH });
        ctx.fillStyle = colours.bg;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        ctx.roundRect(tx, ty, tagW, tagH, tagH * 0.25);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = rig.colour;
        ctx.fillRect(tx, ty, Math.max(3, fontPx * 0.18), tagH);
        ctx.fillStyle = colours.line;
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(name, tx + padX + fontPx * 0.12, ty + tagH / 2 + fontPx * 0.04);
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
      {!anyDriving && <Waiting state={state} />}
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
