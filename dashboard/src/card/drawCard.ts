// Draws the 1080 x 1920 session story card on a canvas (the page shows the canvas and saves it as a PNG).
// Same design language as the TV (DESIGN.md): flat near-black, Saira wide numerals, kerb strip, stripe bundle,
// timing colours only on timing values.

import { formatDelta, formatLapTime, formatRaceTime, ordinal, raceResult } from "../format";
import { IDENTITY_DISPLAY, emptyBounds, extend, fitBounds, project, toMapPlane } from "../map/geometry";
import type { AnyStoryCard, RaceStoryCard, StoryCard } from "../schema";

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

// Pitwall pattern system (DESIGN.md §2): everything leans "/" at 60°; rules are BAR thick on a 2 x BAR pitch.
const SLANT = Math.tan(Math.PI / 6);

/** Steps from the top-right corner: rules growing from the right edge, red and navy (navy a step shorter),
 *  free ends stepping along the slant and cut on it. */
function stripes(ctx: Ctx, accent: string) {
  // Lines: thin vertical hairlines hanging from the top edge, tapering away from the right edge, red lead lines,
  // each fading out toward its free end.
  const pitch = 12;
  const count = 22;
  const tall = 300;
  for (let i = 0; i < count; i++) {
    const lead = i < 2;
    const w = i === 0 ? 6 : lead ? 4 : 2;
    const h = tall * (1 - i / (count + 1)) ** 1.4;
    const fade = ctx.createLinearGradient(0, 0, 0, h);
    fade.addColorStop(0, lead ? accent : "#fff");
    fade.addColorStop(0.6, lead ? accent : "#fff");
    fade.addColorStop(1, "rgba(255,255,255,0)");
    ctx.globalAlpha = lead ? 1 : Math.max(0.12, 0.42 - i * 0.04);
    ctx.fillStyle = fade;
    ctx.fillRect(CARD_W - i * pitch - w, 0, w, h);
  }
  ctx.globalAlpha = 1;
}

/** Double bar (two rules) with the slanted cut end and a separate slanted cap. */
function kerb(ctx: Ctx, x: number, y: number, w: number, h: number, accent: string) {
  const bar = Math.round(h * 0.4);
  const gap = h - bar * 2;
  const cut = h * SLANT;
  const end = x + w - h * 1.8;
  ctx.fillStyle = accent;
  for (const top of [y, y + bar + gap]) {
    const t = (top - y) / h;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(end - cut * t, top);
    ctx.lineTo(end - cut * (t + bar / h), top + bar);
    ctx.lineTo(x, top + bar);
    ctx.closePath();
    ctx.fill();
  }
  const cx = end + h * 0.5;
  ctx.beginPath();
  ctx.moveTo(cx, y);
  ctx.lineTo(cx + h * 0.55, y);
  ctx.lineTo(cx + h * 0.55 - cut, y + h);
  ctx.lineTo(cx - cut, y + h);
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

/** Background, corner lines, kerb and the cafe line shared by both cards. Returns the context, or null. */
function begin(canvas: HTMLCanvasElement, card: AnyStoryCard, accent: string, report: string): Ctx | null {
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = (canvas.getContext?.("2d") ?? null) as Ctx | null;
  if (!ctx) return null;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, CARD_W, CARD_H);
  stripes(ctx, accent);
  kerb(ctx, 0, 0, 420, 12, accent);
  const left = 72;
  ctx.fillStyle = accent;
  ctx.fillRect(left, 118, 22, 22);
  font(ctx, 800, 40, true);
  spaced(ctx, 0.06, 40);
  ctx.fillStyle = C.text;
  ctx.fillText((card.cafe.name || "Live timing").toUpperCase(), left + 38, 140);
  spaced(ctx, 0, 40);
  const date = new Date(card.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  label(ctx, `${report} · ${date}`, left, 210);
  return ctx;
}

/** Draws the story card: the race card for `kind: "race"`, else the session card. */
export function drawCard(canvas: HTMLCanvasElement, card: AnyStoryCard, accent = "#e10600"): void {
  if (card.kind === "race") drawRaceCard(canvas, card, accent);
  else drawSessionCard(canvas, card, accent);
}

function drawSessionCard(canvas: HTMLCanvasElement, card: StoryCard, accent: string): void {
  const ctx = begin(canvas, card, accent, "Session report");
  if (!ctx) return;
  const left = 72;

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

// ---- Race card ------------------------------------------------------------------------------------------

/** What the race card says, worked out from the card data (kept apart from the drawing so it can be tested). */
export interface RaceCardText {
  /** "P4", or DNF / DSQ / NC / RET. */
  big: string;
  /** "Race · Silverstone". */
  title: string;
  /** "P7 → P4", or null without a grid position. */
  grid: string | null;
  /** "+3 places", "−2 places", "Held position", or null. */
  gained: string | null;
  gainedTone: "up" | "down" | "flat";
  best: string;
  total: string;
  penalties: string | null;
  laps: string;
  /** "1st of 4 at <cafe>" (or "Raced at <cafe>" alone). */
  cafe: string;
}

export function raceCardText(card: RaceStoryCard): RaceCardText {
  const g = card.positions_gained;
  const places = (n: number) => `${n} place${n === 1 ? "" : "s"}`;
  const cafeName = card.cafe.name || "the cafe";
  const best = card.best_lap_ms ?? card.best_ms;
  return {
    big: raceResult(card.status, card.position),
    title: `${card.session_type && card.session_type !== "Race" ? card.session_type : "Race"} · ${card.track_name ?? "Track"}`,
    grid: card.grid_position ? `P${card.grid_position} → P${card.position}` : null,
    gained: g == null ? null : g > 0 ? `+${places(g)}` : g < 0 ? `−${places(-g)}` : "Held position",
    gainedTone: g == null || g === 0 ? "flat" : g > 0 ? "up" : "down",
    best: best ? formatLapTime(best) : "–",
    total: formatRaceTime(card.total_time_s),
    penalties: card.penalties_s > 0 ? `+${card.penalties_s} s penalty` : null,
    laps: String(card.laps),
    cafe: card.cafe_drivers >= 2 ? `${ordinal(card.cafe_rank)} of ${card.cafe_drivers} at ${cafeName}`
      : `Raced at ${cafeName}`,
  };
}

function drawRaceCard(canvas: HTMLCanvasElement, card: RaceStoryCard, accent: string): void {
  const ctx = begin(canvas, card, accent, "Race report");
  if (!ctx) return;
  const t = raceCardText(card);
  const left = 72;
  const width = CARD_W - left * 2;

  // The result, huge.
  const bigSize = fitText(ctx, t.big, 900, 360, width - 160, true);
  ctx.fillStyle = card.position === 1 && card.status === "finished" ? accent : C.text;
  const bigBottom = 260 + bigSize * 0.78;
  ctx.fillText(t.big, left - 10, bigBottom);
  if (card.num_cars && t.big.startsWith("P")) {
    const w = ctx.measureText(t.big).width;
    label(ctx, `of ${card.num_cars}`, left + w + 10, bigBottom - 14, C.text2, 40);
  }
  label(ctx, t.title, left, bigBottom + 76, C.text, 40);

  // Driver.
  const name = card.driver.toUpperCase();
  const nameSize = fitText(ctx, name, 900, 130, width, true);
  ctx.fillStyle = C.text;
  const nameY = bigBottom + 110 + nameSize * 0.95;
  ctx.fillText(name, left, nameY);
  label(ctx, card.rig_name, left, nameY + 56, C.text2, 30);

  // Stats.
  const gridY = nameY + 170;
  ctx.fillStyle = C.line;
  ctx.fillRect(left, gridY - 50, width, 2);
  const col2 = CARD_W / 2 + 10;
  stat(ctx, left, gridY, "Grid → finish", t.grid ?? t.big, null);
  if (t.gained) {
    const tone = t.gainedTone === "up" ? C.green : t.gainedTone === "down" ? C.yellow : C.text2;
    label(ctx, t.gained, left, gridY + 136, tone, 32);
  }
  stat(ctx, col2, gridY, "Best lap", t.best, null, C.text);
  stat(ctx, left, gridY + 200, "Race time", t.total, null);
  if (t.penalties) label(ctx, t.penalties, left, gridY + 336, C.yellow, 30);
  stat(ctx, col2, gridY + 200, "Laps", t.laps, null);

  // The cafe result.
  const cafeY = gridY + 430;
  ctx.fillStyle = C.line;
  ctx.fillRect(left, cafeY - 50, width, 2);
  tab(ctx, "Cafe result", card.cafe_drivers >= 2 ? `${card.cafe_drivers} drivers` : null, left, cafeY, accent);
  const cafeText = t.cafe.toUpperCase();
  const cafeSize = fitText(ctx, cafeText, 900, 84, width, true);
  ctx.fillStyle = C.text;
  ctx.fillText(cafeText, left, cafeY + 60 + cafeSize);

  // Slanted flash blocks above the footer (the pattern system: 60° lean, red and navy).
  const flashY = CARD_H - 290;
  const h = 100;
  const d = h * SLANT;
  [[0, 300, accent], [330, 380, "#22324D"], [410, 425, accent]].forEach(([x0, x1, fill]) => {
    ctx.fillStyle = fill as string;
    ctx.beginPath();
    ctx.moveTo(left + (x0 as number) + d, flashY);
    ctx.lineTo(left + (x1 as number) + d, flashY);
    ctx.lineTo(left + (x1 as number), flashY + h);
    ctx.lineTo(left + (x0 as number), flashY + h);
    ctx.closePath();
    ctx.fill();
  });

  kerb(ctx, CARD_W - 420, CARD_H - 12, 420, 12, accent);
  font(ctx, 700, 34, true);
  ctx.fillStyle = C.text;
  ctx.fillText("COME BACK AND RACE AGAIN.", left, CARD_H - 80);
}
