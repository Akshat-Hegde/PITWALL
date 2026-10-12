// Draws the 1080 x 1920 session story card on a canvas (the page shows the canvas and saves it as a PNG).
// Same design language as the TV (DESIGN.md): flat near-black, Saira wide numerals, kerb strip, stripe bundle,
// timing colours only on timing values.

import { formatDelta, formatLapTime } from "../format";
import { IDENTITY_DISPLAY, emptyBounds, extend, fitBounds, project, toMapPlane } from "../map/geometry";
import type { StoryCard } from "../schema";

export const CARD_W = 1080;
export const CARD_H = 1920;

const C = {
  bg: "#0c0d11",
  panel: "#14151b",
  line: "rgba(255,255,255,0.10)",
  text: "#ffffff",
  text2: "rgba(255,255,255,0.58)",
  text3: "rgba(255,255,255,0.34)",
  purple: "#b46cff",
  green: "#38d97a",
  yellow: "#f2c230",
  track: "rgba(255,255,255,0.22)",
};
const FONT = '"Saira Variable", "Saira", "Segoe UI", sans-serif';
const COND = '"Saira Condensed", "Saira Variable", "Segoe UI", sans-serif';

type Ctx = CanvasRenderingContext2D & { fontStretch?: string; letterSpacing?: string };

function font(ctx: Ctx, weight: number, size: number, wide: boolean, family = FONT) {
  ctx.font = `${weight} ${size}px ${family}`;
  if ("fontStretch" in ctx) ctx.fontStretch = wide ? "expanded" : "normal";
}

function spaced(ctx: Ctx, em: number, size: number) {
  if ("letterSpacing" in ctx) ctx.letterSpacing = `${em * size}px`;
}

/** Fit text to a width by shrinking the font size. Returns the size used. */
function fitText(ctx: Ctx, text: string, weight: number, max: number, width: number, wide: boolean): number {
  let size = max;
  font(ctx, weight, size, wide);
  while (size > 24 && ctx.measureText(text).width > width) {
    size -= 4;
    font(ctx, weight, size, wide);
  }
  return size;
}

function label(ctx: Ctx, text: string, x: number, y: number, colour = C.text2, size = 26) {
  font(ctx, 600, size, false, COND);
  spaced(ctx, 0.14, size);
  ctx.fillStyle = colour;
  ctx.fillText(text.toUpperCase(), x, y);
  spaced(ctx, 0, size);
}

/** Stepped speed bars from the top-right corner: red and navy bars ending on a slanted diagonal. */
function stripes(ctx: Ctx, accent: string) {
  const bars = 11;
  const pitch = 22;
  const thick = 12;
  for (let i = 0; i < bars; i++) {
    const y = 40 + i * pitch;
    const len = 420 - i * 30 - (i % 3 === 1 ? 70 : 0);
    const x = CARD_W - len;
    ctx.fillStyle = i % 2 ? "#22324D" : accent;
    ctx.globalAlpha = i % 2 ? 0.9 : 1 - i * 0.05;
    ctx.beginPath();
    ctx.moveTo(x + 11, y);
    ctx.lineTo(CARD_W, y);
    ctx.lineTo(CARD_W, y + thick);
    ctx.lineTo(x, y + thick);
    ctx.closePath();
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

/** Double bar with a slanted cut end and a separate slanted cap (motif 8). */
function kerb(ctx: Ctx, x: number, y: number, w: number, h: number, accent: string) {
  const bar = Math.round(h * 0.38);
  const gap = h - bar * 2;
  const slant = h * 0.8;
  const end = x + w - h * 1.6;
  ctx.fillStyle = accent;
  for (const [top, inset] of [[y, 0], [y + bar + gap, slant * 0.3]] as const) {
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(end - inset, top);
    ctx.lineTo(end - inset - slant * (bar / h), top + bar);
    ctx.lineTo(x, top + bar);
    ctx.closePath();
    ctx.fill();
  }
  ctx.beginPath();
  ctx.moveTo(end + h * 0.5, y);
  ctx.lineTo(end + h * 0.5 + h * 0.5, y);
  ctx.lineTo(end + h * 0.5 + h * 0.5 - slant, y + h);
  ctx.lineTo(end + h * 0.5 - slant, y + h);
  ctx.closePath();
  ctx.fill();
}

/** Angled tab: white left part, accent right part. */
function tab(ctx: Ctx, left: string, right: string | null, x: number, y: number, accent: string) {
  const size = 28;
  font(ctx, 700, size, false, COND);
  spaced(ctx, 0.1, size);
  const pad = 20;
  const slant = 16;
  const lw = ctx.measureText(left.toUpperCase()).width + pad * 2;
  const h = 48;
  ctx.fillStyle = C.text;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + lw, y);
  ctx.lineTo(x + lw - slant, y + h);
  ctx.lineTo(x, y + h);
  ctx.fill();
  ctx.fillStyle = C.bg;
  ctx.fillText(left.toUpperCase(), x + pad, y + 34);
  if (right) {
    const rw = ctx.measureText(right.toUpperCase()).width + pad * 2 + slant;
    const rx = x + lw - slant + 4;
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.moveTo(rx + slant, y);
    ctx.lineTo(rx + rw, y);
    ctx.lineTo(rx + rw - slant, y + h);
    ctx.lineTo(rx, y + h);
    ctx.fill();
    ctx.fillStyle = C.text;
    ctx.fillText(right.toUpperCase(), rx + slant + pad - 4, y + 34);
  }
  spaced(ctx, 0, size);
}

function stat(ctx: Ctx, x: number, y: number, name: string, value: string, unit: string | null, colour = C.text) {
  label(ctx, name, x, y);
  font(ctx, 800, 76, true);
  ctx.fillStyle = colour;
  ctx.fillText(value, x, y + 86);
  if (unit) {
    const w = ctx.measureText(value).width;
    font(ctx, 500, 30, false);
    ctx.fillStyle = C.text3;
    ctx.fillText(unit.toUpperCase(), x + w + 12, y + 86);
  }
}

const RATING_COLOUR: Record<string, string> = { purple: C.purple, green: C.green, yellow: C.yellow };

function miniMap(ctx: Ctx, card: StoryCard, x: number, y: number, w: number, h: number) {
  const outline = card.outline;
  if (!outline || outline.points.length < 3) {
    label(ctx, "Track map after the first clean lap of the day", x, y + h / 2, C.text3);
    return;
  }
  const display = outline.display ?? IDENTITY_DISPLAY;
  const bounds = emptyBounds();
  for (const [px, pz] of outline.points) {
    const [mx, my] = toMapPlane(px, pz, display);
    extend(bounds, mx, my);
  }
  const fit = fitBounds(bounds, w, h, 30);
  const pts = outline.points.map(([px, pz]) => {
    const [mx, my] = toMapPlane(px, pz, display);
    const [sx, sy] = project(fit, mx, my);
    return [x + sx, y + sy] as [number, number];
  });
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = C.track;
  ctx.lineWidth = 12;
  ctx.beginPath();
  pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
  ctx.closePath();
  ctx.stroke();
  const minis = card.minis;
  if (minis) {
    const n = pts.length;
    ctx.lineWidth = 12;
    ctx.lineCap = "butt";
    minis.forEach((m, k) => {
      const from = Math.floor((k / minis.length) * n);
      const to = Math.floor(((k + 1) / minis.length) * n);
      ctx.strokeStyle = RATING_COLOUR[m.rating] ?? C.track;
      ctx.beginPath();
      for (let i = from; i <= to; i++) {
        const [px, py] = pts[i % n]!;
        if (i === from) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
    });
  }
  // start / finish tick
  const [ax, ay] = pts[0]!;
  const [bx, by] = pts[1]!;
  const len = Math.hypot(bx - ax, by - ay) || 1;
  const nx = -(by - ay) / len;
  const ny = (bx - ax) / len;
  ctx.strokeStyle = C.text;
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(ax - nx * 24, ay - ny * 24);
  ctx.lineTo(ax + nx * 24, ay + ny * 24);
  ctx.stroke();
}

export function drawCard(canvas: HTMLCanvasElement, card: StoryCard, accent = "#e10600"): void {
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d") as Ctx | null;
  if (!ctx) return;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, CARD_W, CARD_H);
  stripes(ctx, accent);
  kerb(ctx, 0, 0, 420, 12, accent);

  const left = 72;
  // cafe
  ctx.fillStyle = accent;
  ctx.fillRect(left, 118, 22, 22);
  font(ctx, 800, 40, true);
  spaced(ctx, 0.06, 40);
  ctx.fillStyle = C.text;
  ctx.fillText((card.cafe.name || "Live timing").toUpperCase(), left + 38, 140);
  spaced(ctx, 0, 40);
  const date = new Date(card.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  label(ctx, `Session report · ${date}`, left, 210);

  // driver
  const name = card.driver.toUpperCase();
  const size = fitText(ctx, name, 900, 150, CARD_W - left * 2, true);
  ctx.fillStyle = C.text;
  ctx.fillText(name, left, 250 + size * 0.95);
  label(ctx, `${card.track_name ?? "Track"} · ${card.rig_name}`, left, 300 + size, C.text2, 32);

  // best lap
  const bestY = 420 + size;
  tab(ctx, "Best lap", card.best_lap_class === "pro" ? "Pro" : null, left, bestY, accent);
  const record = card.today_position === 1;
  font(ctx, 900, 190, true);
  ctx.fillStyle = record ? C.purple : C.text;
  ctx.fillText(formatLapTime(card.best_ms), left - 6, bestY + 230);
  if (card.today_position) {
    label(ctx, record ? "Fastest today" : `P${card.today_position} of ${card.today_drivers} today`, left,
          bestY + 290, record ? C.purple : C.text2, 30);
  }

  // stats grid
  const gridY = bestY + 380;
  ctx.fillStyle = C.line;
  ctx.fillRect(left, gridY - 50, CARD_W - left * 2, 2);
  const col2 = CARD_W / 2 + 10;
  stat(ctx, left, gridY, "Top speed", card.top_speed_kph ? String(card.top_speed_kph) : "–", "km/h");
  stat(ctx, col2, gridY, "Theoretical best", formatLapTime(card.theoretical_ms), null);
  stat(ctx, left, gridY + 170, "Laps", String(card.laps), `in ${card.session_minutes} min`);
  if (card.improvement) {
    const d = card.improvement.delta_ms;
    stat(ctx, col2, gridY + 170, "Since last visit", formatDelta(d), null, d < 0 ? C.green : C.yellow);
  } else {
    stat(ctx, col2, gridY + 170, "Since last visit", "First visit", null, C.text2);
  }

  // mini-sector map
  const mapY = gridY + 330;
  ctx.fillStyle = C.line;
  ctx.fillRect(left, mapY - 40, CARD_W - left * 2, 2);
  label(ctx, "Best lap, 24 mini-sectors", left, mapY + 10);
  const mapH = CARD_H - mapY - 260;
  miniMap(ctx, card, left, mapY + 30, CARD_W - left * 2, Math.max(300, mapH));
  const legendY = CARD_H - 190;
  let lx = left;
  for (const [text, colour] of [["Fastest today", C.purple], ["Own best", C.green], ["Slower", C.yellow]] as const) {
    ctx.fillStyle = colour;
    ctx.fillRect(lx, legendY - 12, 36, 8);
    label(ctx, text, lx + 48, legendY, C.text2, 24);
    font(ctx, 600, 24, false, COND);
    spaced(ctx, 0.14, 24);
    lx += 48 + ctx.measureText(text.toUpperCase()).width + 48;
    spaced(ctx, 0, 24);
  }

  // footer
  kerb(ctx, CARD_W - 420, CARD_H - 12, 420, 12, accent);
  font(ctx, 700, 34, true);
  ctx.fillStyle = C.text;
  ctx.fillText("COME BACK AND BEAT IT.", left, CARD_H - 80);
}
