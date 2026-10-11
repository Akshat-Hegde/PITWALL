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
import { MINI_SECTORS } from "../state/laptrace";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { Waiting } from "./Waiting";

interface Props {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  /** From ?map=...: overrides the outline's display transform (orientation check). */
  displayOverride: Display | null;
  /** "live": every car with its name label, mini-sectors in the colour of the rig fastest through each.
   *  "mini": a small map with one car (MULTIVIEW tiles), no labels. */
  variant?: "live" | "mini";
  /** Only this rig's car (mini maps). */
  onlyRigId?: string | null;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Canvas map (DESIGN.md): a thin neutral line, mini-sectors in the colour of the rig fastest through each,
 * small car dots with name labels off the track on thin leader lines. Redrawn every animation frame; dots are
 * interpolated between the 15 Hz frames.
 */
export function TrackMap({ store, state, trackKey, displayOverride, variant = "live", onlyRigId = null }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Latest React state for the draw loop, without restarting it on every frame message.
  const stateRef = useRef(state);
  stateRef.current = state;
  const trackKeyRef = useRef(trackKey);
  trackKeyRef.current = trackKey;
  const overrideRef = useRef(displayOverride);
  overrideRef.current = displayOverride;
  const onlyRef = useRef(onlyRigId);
  onlyRef.current = onlyRigId;
  const mini = variant === "mini";
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
    let rem = 20;
    let c = { track: "", text: "", text3: "", bg: "", purple: "", green: "", yellow: "", font: "sans-serif" };

    const resize = () => {
      // Draw in layout pixels (the 1920 x 1080 canvas); the backing store matches the screen, so a 4K TV
      // (canvas scaled 2x) gets a sharp map.
      const rect = canvas.getBoundingClientRect();
      width = canvas.clientWidth || rect.width;
      height = canvas.clientHeight || rect.height;
      const k = (window.devicePixelRatio || 1) * (width ? rect.width / width : 1);
      canvas.width = Math.round(width * k);
      canvas.height = Math.round(height * k);
      ctx.setTransform(k, 0, 0, k, 0, 0);
      rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 20;
      c = {
        track: cssVar("--map-track"),
        text: cssVar("--text"),
        text3: cssVar("--text-3"),
        bg: cssVar("--bg"),
        purple: cssVar("--timing-purple"),
        green: cssVar("--timing-green"),
        yellow: cssVar("--timing-yellow"),
        font: cssVar("--font-cond") || "sans-serif",
      };
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    window.addEventListener("resize", resize); // the stage scale changes without the canvas box changing
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
      // Room round the track for the name labels.
      const fit = fitBounds(bounds, width, height, mini ? rem * 0.6 : rem * 3.4);
      const toScreen = (x: number, z: number) => {
        const [px, py] = toMapPlane(x, z, display);
        return project(fit, px, py);
      };
      const lineW = mini ? rem * 0.14 : rem * 0.18;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";

      let centre: [number, number] = [width / 2, height / 2];
      if (outline && outline.points.length > 2) {
        const pts = outline.points.map(([x, z]) => toScreen(x, z));
        centre = [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
        ctx.beginPath();
        pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.closePath();
        ctx.strokeStyle = c.track;
        ctx.lineWidth = lineW;
        ctx.stroke();

        // Mini-sectors in the colour of the rig fastest through each (live map only).
        const owners = !mini && key ? store.laps.miniOwners(key) : null;
        if (owners) {
          const colours = new Map(s.rigs.map((r) => [r.rig_id, r.colour]));
          const n = pts.length;
          owners.forEach((rigId, k) => {
            const from = Math.floor((k / MINI_SECTORS) * n);
            const to = Math.floor(((k + 1) / MINI_SECTORS) * n);
            ctx.beginPath();
            for (let i = from; i <= to; i++) {
              const [x, y] = pts[i % n]!;
              if (i === from) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            }
            ctx.strokeStyle = colours.get(rigId) ?? c.track;
            ctx.lineWidth = lineW;
            ctx.stroke();
          });
        }

        // Start/finish: a short white tick across the track. Sector lines: grey ticks with S2 / S3.
        tick(ctx, pts, 0, rem * 0.7, c.text, rem * 0.18);
        const starts = mini ? null : outline.sector_starts;
        if (starts) {
          ctx.font = `600 ${rem * 0.6}px ${c.font}`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          for (const k of [1, 2]) {
            const i = starts[k]!;
            tick(ctx, pts, i, rem * 0.5, c.text3, rem * 0.1);
            const [x, y] = pts[i % pts.length]!;
            const [dx, dy] = away(centre, x, y);
            ctx.fillStyle = c.text3;
            ctx.fillText(`S${k + 1}`, x + dx * rem * 1.1, y + dy * rem * 1.1);
          }
        }
      }

      // No outline yet: the path driven so far, so the track shape shows.
      if (!outline && key) {
        ctx.strokeStyle = c.track;
        ctx.lineWidth = lineW;
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

      // The dots and labels on top.
      const rigs = onlyRef.current ? s.rigs.filter((r) => r.rig_id === onlyRef.current) : s.rigs;
      const placed: { x: number; y: number; w: number; h: number }[] = [];
      const fontPx = rem * 0.75;
      const r = rem * 0.32;
      for (const rig of rigs) {
        const frame = s.frames[rig.rig_id];
        if (!frame || frame.state !== "driving" || frame.session.track_key !== key) continue;
        const pos = store.trails.positionAt(rig.rig_id, renderAt);
        if (!pos) continue;
        const [sx, sy] = toScreen(pos.x, pos.z);
        if (mini) {
          ctx.beginPath();
          ctx.arc(sx, sy, r * 1.2, 0, Math.PI * 2);
          ctx.fillStyle = rig.colour;
          ctx.fill();
          ctx.lineWidth = rem * 0.1;
          ctx.strokeStyle = c.bg;
          ctx.stroke();
          continue;
        }
        const name = (frame.driver ?? rig.name).toUpperCase();
        ctx.font = `700 ${fontPx}px ${c.font}`;
        const w = ctx.measureText(name).width + rem * 0.5;
        const h = fontPx * 1.3;
        const [dx, dy] = away(centre, sx, sy);
        // Label off the track: try further out, then above / below, until it doesn't cover another label.
        let lx = 0;
        let ly = 0;
        const place = (dist: number, shiftY: number) => {
          const ax = sx + dx * dist;
          const ay = sy + dy * dist + shiftY;
          lx = Math.max(2, Math.min(width - w - 2, dx >= 0 ? ax : ax - w));
          ly = Math.max(2, Math.min(height - h - 2, ay - h / 2));
        };
        const overlaps = () => placed.some((p) => lx < p.x + p.w + 4 && lx + w + 4 > p.x && ly < p.y + p.h + 2 && ly + h + 2 > p.y);
        const shifts = [0, -1.1, 1.1, -2.2, 2.2, -3.3, 3.3];
        let found = false;
        for (let ring = 0; ring < 4 && !found; ring++) {
          for (const k of shifts) {
            place(rem * 2 + ring * rem * 2.2, k * h);
            if (!overlaps()) {
              found = true;
              break;
            }
          }
        }
        if (!found) place(rem * 2, 0);
        placed.push({ x: lx, y: ly, w, h });
        const anchorX = dx >= 0 ? lx : lx + w;
        const anchorY = ly + h / 2;
        // Leader line from the dot to the label.
        ctx.strokeStyle = rig.colour;
        ctx.globalAlpha = 0.8;
        ctx.lineWidth = Math.max(1, rem * 0.06);
        ctx.beginPath();
        ctx.moveTo(sx + dx * r, sy + dy * r);
        ctx.lineTo(anchorX, anchorY);
        ctx.stroke();
        ctx.globalAlpha = 1;
        // Label: rig-colour stripe and the name.
        ctx.fillStyle = rig.colour;
        ctx.fillRect(dx >= 0 ? lx : lx + w - rem * 0.15, ly + h * 0.12, rem * 0.15, h * 0.76);
        ctx.fillStyle = c.text;
        ctx.textAlign = dx >= 0 ? "left" : "right";
        ctx.textBaseline = "middle";
        ctx.fillText(name, dx >= 0 ? lx + rem * 0.35 : lx + w - rem * 0.35, anchorY + fontPx * 0.05);
        // The dot.
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = rig.colour;
        ctx.fill();
        ctx.lineWidth = rem * 0.1;
        ctx.strokeStyle = c.bg;
        ctx.stroke();
      }
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [store, mini]);

  const hasOutline = trackKey ? Boolean(state.outlines[trackKey]) : false;
  const anyDriving = Object.values(state.frames).some((f) => f.state === "driving");
  if (mini) {
    return (
      <div className="track-map track-map--mini">
        <canvas ref={canvasRef} className="track-map__canvas" aria-hidden="true" />
      </div>
    );
  }
  return (
    <div className="track-map">
      <canvas ref={canvasRef} className="track-map__canvas" aria-label="Track map with live car positions" />
      {!anyDriving && <Waiting state={state} />}
      {anyDriving && !hasOutline && (
        <p className="track-map__note track-map__note--corner">The track outline appears after the first full lap.</p>
      )}
      {displayOverride && (
        <p className="track-map__note track-map__note--top">Map orientation: {describeDisplay(displayOverride)}</p>
      )}
    </div>
  );
}

/** Unit vector from the track's centre towards (x, y): labels go this way, off the track. */
export function away(centre: [number, number], x: number, y: number): [number, number] {
  const dx = x - centre[0];
  const dy = y - centre[1];
  const len = Math.hypot(dx, dy) || 1;
  return [dx / len, dy / len];
}

/** A short line across the track at outline point i. */
function tick(ctx: CanvasRenderingContext2D, pts: [number, number][], i: number, half: number, colour: string,
              lineWidth: number) {
  const n = pts.length;
  const [ax, ay] = pts[i % n]!;
  const [bx, by] = pts[(i + 1) % n]!;
  const len = Math.hypot(bx - ax, by - ay) || 1;
  const nx = -(by - ay) / len;
  const ny = (bx - ax) / len;
  ctx.strokeStyle = colour;
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "butt";
  ctx.beginPath();
  ctx.moveTo(ax - nx * half, ay - ny * half);
  ctx.lineTo(ax + nx * half, ay + ny * half);
  ctx.stroke();
  ctx.lineCap = "round";
}
