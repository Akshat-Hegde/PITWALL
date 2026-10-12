import { useEffect, useRef } from "react";
import { IDENTITY_DISPLAY, emptyBounds, extend, fitBounds, isEmpty, project, toMapPlane, type Display } from "../map/geometry";
import { MINI_SECTORS } from "../state/laptrace";
import type { RefLap } from "../state/pitwall";
import type { DashboardState } from "../state/reducer";
import type { DashboardStore } from "../state/store";
import { useTvScale } from "./Stage";

// The Pitwall LIVE map (design "Pitwall TV", Turn 2): a glowing track casing over a dark bed, thin
// mini-sector bands (the rig fastest through each, or for one rig how the lap compares with their best),
// sector ticks and labels, a chequered start/finish, dashed ghosts of the reference laps, and every car with
// its name box on a leader line; the hottest lap gets a breathing ring. Drawn every animation frame.

export interface Ghost {
  ref: RefLap;
  colour: string;
  label: string;
}

interface Props {
  store: DashboardStore;
  state: DashboardState;
  trackKey: string | null;
  /** The hottest lap: ringed, and the ghosts run against its lap time. */
  focusRigId: string | null;
  /** One rig: mini-sectors show the focus lap against their best instead of who owns each one. */
  solo: boolean;
  ghosts: Ghost[];
  displayOverride?: Display | null;
}

const BAND_EMPTY = "#262930";
const BAND_MISSED = "#5A5E68";
const K = 592 / 840; // the design's SVG units to our pixels

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PitwallMap({ store, state, trackKey, focusRigId, solo, ghosts, displayOverride = null }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const live = useRef({ state, trackKey, focusRigId, solo, ghosts, displayOverride });
  live.current = { state, trackKey, focusRigId, solo, ghosts, displayOverride };
  const scale = useTvScale();

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let raf = 0;
    const font = cssVar("--font-cond") || "sans-serif";
    const ghostT = new Map<string, number>(); // smoothed ghost distance per label

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const { state: s, trackKey: key, focusRigId: focus, solo: one, ghosts: gs, displayOverride: ov } = live.current;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const k = (window.devicePixelRatio || 1) * scale;
      if (canvas.width !== Math.round(w * k)) canvas.width = Math.round(w * k);
      if (canvas.height !== Math.round(h * k)) canvas.height = Math.round(h * k);
      ctx.setTransform(k, 0, 0, k, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const outline = key ? s.outlines[key] : undefined;
      if (!outline || outline.points.length < 3) return;
      const display = ov ?? outline.display ?? IDENTITY_DISPLAY;
      const b = emptyBounds();
      for (const [x, z] of outline.points) {
        const [px, py] = toMapPlane(x, z, display);
        extend(b, px, py);
      }
      if (isEmpty(b)) return;
      const fit = fitBounds(b, w, h, 48);
      const scr = (x: number, z: number) => {
        const [px, py] = toMapPlane(x, z, display);
        return project(fit, px, py);
      };
      const pts = outline.points.map(([x, z]) => scr(x, z));
      const n = pts.length;
      const cx = pts.reduce((a, p) => a + p[0], 0) / n;
      const cy = pts.reduce((a, p) => a + p[1], 0) / n;
      const outward = (i: number): [number, number] => {
        const [ax, ay] = pts[(i - 1 + n) % n]!;
        const [bx, by] = pts[(i + 1) % n]!;
        const len = Math.hypot(bx - ax, by - ay) || 1;
        let nx = -(by - ay) / len;
        let ny = (bx - ax) / len;
        const [px, py] = pts[i % n]!;
        if (nx * (px - cx) + ny * (py - cy) < 0) {
          nx = -nx;
          ny = -ny;
        }
        return [nx, ny];
      };
      const atFrac = (f: number): { x: number; y: number; i: number } => {
        const x = (((f % 1) + 1) % 1) * n;
        const i = Math.floor(x);
        const u = x - i;
        const [ax, ay] = pts[i % n]!;
        const [bx, by] = pts[(i + 1) % n]!;
        return { x: ax + (bx - ax) * u, y: ay + (by - ay) * u, i };
      };
      const path = (from = 0, to = n) => {
        ctx.beginPath();
        for (let i = from; i <= to; i++) {
          const [x, y] = pts[i % n]!;
          if (i === from) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      };
      ctx.lineJoin = "round";
      ctx.lineCap = "butt";

      // Casing with a red glow, then the dark bed.
      path();
      ctx.closePath();
      ctx.save();
      ctx.shadowColor = "rgba(225,6,0,0.45)";
      ctx.shadowBlur = 10 * k;
      ctx.strokeStyle = "rgba(255,255,255,0.24)";
      ctx.lineWidth = 24 * K;
      ctx.stroke();
      ctx.restore();
      ctx.strokeStyle = "#0E1014";
      ctx.lineWidth = 20 * K;
      ctx.stroke();

      // Mini-sector bands.
      const colours = new Map(s.rigs.map((r) => [r.rig_id, r.colour]));
      const focusColour = focus ? colours.get(focus) ?? "#fff" : "#fff";
      const today = s.leaderboards.today;
      const owners = (key ? store.laps.miniOwners(key) : null)
        ?? (today && today.track_key === key ? today.mini_owners ?? null : null);
      const liveMinis = one && focus ? store.laps.liveMinis(focus) : null;
      for (let m = 0; m < MINI_SECTORS; m++) {
        let c = BAND_EMPTY;
        if (one) {
          const r = liveMinis && liveMinis.trackKey === key ? liveMinis.ratings[m] : undefined;
          if (r === "purple" || r === "green") c = focusColour;
          else if (r) c = BAND_MISSED;
        } else if (owners?.[m]) {
          c = colours.get(owners[m]!) ?? BAND_MISSED;
        }
        path(Math.floor((m / MINI_SECTORS) * n), Math.floor(((m + 1) / MINI_SECTORS) * n));
        ctx.strokeStyle = c;
        ctx.lineWidth = 6 * K;
        ctx.stroke();
      }

      // Start/finish and sector ticks, sector labels between them.
      const starts = outline.sector_starts ?? [0, Math.floor(n / 3), Math.floor((2 * n) / 3)];
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 3 * K;
      for (const i of starts) {
        const [x, y] = pts[i % n]!;
        const [nx, ny] = outward(i);
        ctx.beginPath();
        ctx.moveTo(x - nx * 16 * K, y - ny * 16 * K);
        ctx.lineTo(x + nx * 16 * K, y + ny * 16 * K);
        ctx.stroke();
      }
      ctx.font = `700 15px ${font}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#8A8F9C";
      starts.forEach((start, j) => {
        const end = j < 2 ? starts[j + 1]! : n;
        const mid = Math.floor((start + end) / 2) % n;
        const [x, y] = pts[mid]!;
        const [nx, ny] = outward(mid);
        ctx.fillText(`S${j + 1}`, x + nx * 40 * K, y + ny * 40 * K);
      });
      // Chequered start/finish block.
      {
        const [x, y] = pts[0]!;
        const [nx, ny] = outward(0);
        const bx = x + nx * 30 * K - 6;
        const by = y + ny * 30 * K - 8;
        for (let r = 0; r < 3; r++) {
          for (let c2 = 0; c2 < 2; c2++) {
            ctx.fillStyle = (r + c2) % 2 ? "#0B0C0F" : "#fff";
            ctx.fillRect(bx + c2 * 6, by + r * 5.33, 6, 5.34);
          }
        }
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1;
        ctx.strokeRect(bx, by, 12, 16);
      }

      // Ghosts: where the reference laps would be at the focus lap's current time.
      const ff = focus ? s.frames[focus] : undefined;
      const lap = ff?.state === "driving" ? ff.lap : null;
      if (lap && lap.distance_m >= 0) {
        const hist = focus ? store.live.history(focus) : [];
        const lastT = hist.length ? hist[hist.length - 1]!.t : now;
        const lapT = lap.current_ms + Math.min(150, Math.max(0, now - lastT));
        for (const g of gs) {
          const target = g.ref.distAt(lapT) / g.ref.length;
          const prev = ghostT.get(g.label);
          const f = prev == null || Math.abs(target - prev) > 0.05 ? target : prev + (target - prev) * 0.35;
          ghostT.set(g.label, f);
          const p = atFrac(f);
          const [nx, ny] = outward(p.i);
          ctx.save();
          ctx.globalAlpha = 0.75;
          ctx.setLineDash([4 * K, 3 * K]);
          ctx.strokeStyle = g.colour;
          ctx.lineWidth = 2.5 * K;
          ctx.beginPath();
          ctx.arc(p.x, p.y, 9 * K, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
          ctx.font = `700 12px ${font}`;
          ctx.fillStyle = g.colour;
          ctx.textAlign = nx > 0 ? "right" : "left";
          ctx.fillText(g.label, p.x - nx * 30 * K, p.y - ny * 30 * K);
        }
      }

      // Cars: leader line, name box, dot; the hottest lap ringed.
      const placed: { x: number; y: number; w: number; h: number }[] = [];
      const renderAt = now - 1000 / s.frameHz;
      for (const rig of s.rigs) {
        const frame = s.frames[rig.rig_id];
        if (!frame || frame.state !== "driving" || frame.session.track_key !== key) continue;
        const pos = store.trails.positionAt(rig.rig_id, renderAt);
        if (!pos) continue;
        const [sx, sy] = scr(pos.x, pos.z);
        let best = 0;
        let bestD = Infinity;
        for (let i = 0; i < n; i++) {
          const d = (pts[i]![0] - sx) ** 2 + (pts[i]![1] - sy) ** 2;
          if (d < bestD) {
            bestD = d;
            best = i;
          }
        }
        const [nx, ny] = outward(best);
        const name = (frame.driver ?? rig.name).toUpperCase();
        ctx.font = `700 15px ${font}`;
        const bw = ctx.measureText(name).width + 24;
        const bh = 32 * K;
        const right = nx >= -0.15;
        let dist = 58 * K;
        let bx = 0;
        let by = 0;
        for (let tries = 0; tries < 4; tries++) {
          const lx = sx + nx * dist;
          const ly = sy + ny * dist;
          bx = Math.max(2, Math.min(w - bw - 2, right ? lx : lx - bw));
          by = Math.max(2, Math.min(h - bh - 2, ly - bh / 2));
          const clash = placed.some((q) => bx < q.x + q.w + 4 && bx + bw + 4 > q.x && by < q.y + q.h + 3 && by + bh + 3 > q.y);
          if (!clash) break;
          dist += 26;
        }
        placed.push({ x: bx, y: by, w: bw, h: bh });
        ctx.strokeStyle = "rgba(255,255,255,0.35)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(sx + nx * 12 * K, sy + ny * 12 * K);
        ctx.lineTo(right ? bx : bx + bw, by + bh / 2);
        ctx.stroke();
        ctx.fillStyle = "#0B0C0F";
        ctx.fillRect(bx, by, bw, bh);
        ctx.strokeStyle = "rgba(255,255,255,0.12)";
        ctx.lineWidth = 1;
        ctx.strokeRect(bx + 0.5, by + 0.5, bw - 1, bh - 1);
        ctx.fillStyle = rig.colour;
        ctx.fillRect(bx, by, 5 * K, bh);
        ctx.fillStyle = "#fff";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(name, bx + 14 * K, by + bh / 2 + 1);
        if (rig.rig_id === focus) {
          ctx.save();
          ctx.globalAlpha = 0.9;
          ctx.strokeStyle = rig.colour;
          ctx.lineWidth = 2.5 * K;
          ctx.beginPath();
          ctx.arc(sx, sy, (19 + 3 * Math.sin(now / 250)) * K, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
        ctx.save();
        ctx.shadowColor = rig.colour;
        ctx.shadowBlur = 6 * k;
        ctx.beginPath();
        ctx.arc(sx, sy, 9 * K, 0, Math.PI * 2);
        ctx.fillStyle = rig.colour;
        ctx.fill();
        ctx.restore();
        ctx.lineWidth = 3 * K;
        ctx.strokeStyle = "#0B0C0F";
        ctx.stroke();
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [store, scale]);

  return <canvas ref={ref} className="pwmap__canvas" aria-label="Track map with live car positions" />;
}
