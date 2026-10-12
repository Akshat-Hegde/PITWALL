// The design motifs from docs/DESIGN.md §2, drawn in SVG/CSS. Nothing here is taken from a reference file.

type Corner = "top-right" | "bottom-left" | "top-left" | "bottom-right";

// ---- The Pitwall pattern system (DESIGN.md §2) ------------------------------------------------------
// One slant, one bar module, one palette, two compositions:
//   slant    every slash, bar end, hatch and streak leans "/" at 60° from horizontal
//   module   bars are BAR thick on a PITCH grid; hairlines are 2 units
//   palette  red (brand accent), navy, and white at low strength
//   Flash    corner composition: slanted blocks (wide, medium, thin, hairline trail) with stepped rules
//   Lines    edge composition: thin vertical hairlines tapering away from an edge, red lead lines
export const SLANT = Math.tan((30 * Math.PI) / 180); // horizontal run per unit of height for a 60° lean
export const BAR = 6;
export const PITCH = 12;
export const RED = "var(--brand-accent, #E10600)";
export const NAVY = "#22324D";

/** A block leaning "/": its top edge spans [x0, x1]; the bottom edge is shifted left by h x SLANT. */
function block(x0: number, x1: number, y: number, h: number): string {
  const d = h * SLANT;
  return `M${x0} ${y} H${x1} L${x1 - d} ${y + h} H${x0 - d} Z`;
}

/** A rule (bar) from the left edge, its free right end cut on the slant. */
function ruleFromLeft(len: number, y: number, h: number): string {
  return `M0 ${y} H${len} L${len - h * SLANT} ${y + h} H0 Z`;
}

/** A rule from the right edge of a box of width w, its free left end cut on the slant. */
function ruleFromRight(w: number, len: number, y: number, h: number): string {
  return `M${w - len + h * SLANT} ${y} H${w} V${y + h} H${w - len} Z`;
}

/**
 * Flash: the corner composition. Slanted blocks come in from the corner (wide, medium, thin, then a trail of
 * hairlines fading out), with three stepped rules (red, navy, red) along the inner edge; the whole thing fades
 * away from the corner. Native geometry for the top corners; bottom corners are the top ones turned 180°
 * (which keeps the "/" lean).
 */
export function Flash({ width, height, corner = "top-right", rules = true, dots = false, className = "" }: {
  width: number; height: number; corner?: Corner; rules?: boolean; dots?: boolean; className?: string;
}) {
  const right = corner === "top-right" || corner === "bottom-left";
  const turned = corner.startsWith("bottom");
  const W = width;
  const H = height;
  const id = `flash-${corner}-${W}x${H}`;
  const widths = [0.3, 0.1, 0.035].map((f) => Math.max(BAR, f * W));
  const gap = PITCH;
  const paths: { d: string; fill: string; opacity: number }[] = [];
  let edge = 0; // distance from the anchor edge along the top row
  widths.forEach((w, i) => {
    const x0 = right ? W + H * SLANT - edge - w : edge;
    paths.push({ d: block(x0, x0 + w, 0, H), fill: RED, opacity: 1 });
    edge += w + gap * (i === 0 ? 1.3 : 1);
  });
  for (let k = 0; k < 7; k++) {
    const x0 = right ? W + H * SLANT - edge - 2 : edge;
    paths.push({ d: block(x0, x0 + 2, 0, H), fill: RED, opacity: 0.85 - k * 0.11 });
    edge += 2 + gap;
  }
  if (rules) {
    const top = H * 0.55;
    [0.42, 0.62, 0.3].forEach((f, i) => {
      const y = top + i * (BAR + BAR * 0.5);
      if (y + BAR > H) return;
      const len = f * W;
      paths.push({ d: right ? ruleFromRight(W, len, y, BAR) : ruleFromLeft(len, y, BAR), fill: i === 1 ? NAVY : RED, opacity: 1 });
    });
  }
  return (
    <svg className={`flash ${className}`} viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-fade`} x1={right ? 1 : 0} y1={0} x2={right ? 0.15 : 0.85} y2={1}>
          <stop offset="0" stopColor="#fff" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0.9" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}-mask`}><rect width={W} height={H} fill={`url(#${id}-fade)`} /></mask>
        {dots && (
          <pattern id={`${id}-dots`} width="7" height="7" patternUnits="userSpaceOnUse">
            <circle cx="3.5" cy="3.5" r="1.1" fill="#fff" />
          </pattern>
        )}
      </defs>
      <g mask={`url(#${id}-mask)`} transform={turned ? `rotate(180 ${W / 2} ${H / 2})` : undefined}>
        {dots && <rect width={W} height={H} fill={`url(#${id}-dots)`} opacity={0.12} />}
        {paths.map((p, i) => <path key={i} d={p.d} fill={p.fill} opacity={p.opacity} />)}
      </g>
    </svg>
  );
}

/** Corner flash for the attract, board, moment and portrait screens (one per view, never behind data). */
export function StripeBundle({ corner = "top-right", className = "" }: { corner?: Corner; className?: string }) {
  return <Flash width={440} height={330} corner={corner} dots className={`stripes stripes--${corner} ${className}`} />;
}

/** The flash small, closing the TV header band on the right. */
export function SlashMark({ className = "" }: { className?: string }) {
  return <Flash width={150} height={52} corner="top-right" rules={false} className={`slashmark ${className}`} />;
}

/**
 * Lines: the edge composition. Thin vertical hairlines on a fixed pitch, standing on an edge (top or bottom)
 * and tapering in height away from the side they grow from; the lead lines are red, the rest low white, and
 * each fades out toward its free end.
 */
export function EdgeLines({ width, height, from = "left", anchor = "bottom", red = 2, pitch = 6, className = "" }: {
  width: number; height: number; from?: "left" | "right"; anchor?: "top" | "bottom"; red?: number; pitch?: number;
  className?: string;
}) {
  const count = Math.max(1, Math.floor(width / pitch));
  const id = `edgelines-${anchor}-${width}x${height}`;
  return (
    <svg className={`edgelines ${className}`} viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1={anchor === "bottom" ? 1 : 0} x2="0" y2={anchor === "bottom" ? 0 : 1}>
          <stop offset="0" stopColor="#fff" />
          <stop offset="0.6" stopColor="#fff" stopOpacity="0.7" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}-m`}><rect width={width} height={height} fill={`url(#${id})`} /></mask>
      </defs>
      <g mask={`url(#${id}-m)`}>
        {Array.from({ length: count }, (_, i) => {
          const w = i === 0 ? 3 : i < red ? 2 : 1;
          const h = height * (1 - i / (count + 1)) ** 1.4;
          const x = from === "left" ? i * pitch : width - i * pitch - w;
          const y = anchor === "bottom" ? height - h : 0;
          return <rect key={i} x={x} y={y} width={w} height={h}
                       fill={i < red ? RED : "#fff"} opacity={i < red ? 1 : Math.max(0.12, 0.42 - i * 0.04)} />;
        })}
      </g>
    </svg>
  );
}

/**
 * Motif 2: a double bar with a slanted cut end and a separate slanted cap. value 0..1.
 * tone "accent" (brake, progress) or "light" (throttle).
 */
export function SlantBar({ value, tone = "light", label }: { value: number | null; tone?: "light" | "accent" | "rig";
                                                            label?: string }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <span className={`slant slant--${tone}${value == null || pct < 1 ? " is-empty" : ""}`} role="meter" aria-label={label}
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <span className="slant__fill" style={{ width: `${pct}%` }}>
        <span className="slant__a" />
        <span className="slant__b" />
        <span className="slant__cap" />
      </span>
    </span>
  );
}

/** Motif 4: a row of thin ticks; lit ticks are white and grow toward the top end. */
export function Barcode({ value, max, ticks = 40, className = "" }: { value: number | null; max: number; ticks?: number;
                                                                     className?: string }) {
  const lit = value == null ? 0 : Math.round(Math.max(0, Math.min(1, value / max)) * ticks);
  return (
    <svg className={`barcode ${className}`} viewBox={`0 0 ${ticks * 4} 24`} preserveAspectRatio="none" aria-hidden="true">
      {Array.from({ length: ticks }, (_, i) => {
        const h = 10 + (14 * i) / (ticks - 1);
        return <rect key={i} x={i * 4} y={24 - h} width="2" height={h} className={i < lit ? "is-lit" : ""} />;
      })}
    </svg>
  );
}

/** Motif 5: an angled tab, e.g. LAP 4 | PUSH. The second part sits on the accent. */
export function Tab({ left, right = null, className = "" }: { left: React.ReactNode; right?: React.ReactNode;
                                                             className?: string }) {
  return (
    <span className={`tab-badge ${className}`}>
      <span className="tab-badge__left">{left}</span>
      {right != null && <span className="tab-badge__right">{right}</span>}
    </span>
  );
}

/** Initials of a driver name: "Maya Rao" -> "MR", "NightShift_Nico" -> "NN". */
export function initials(name: string): string {
  const parts = name.replace(/[^\p{L}\p{N}]+/gu, " ").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) {
    const caps = parts[0]!.match(/\p{Lu}/gu);
    return (caps && caps.length >= 2 ? caps.slice(0, 2).join("") : parts[0]!.slice(0, 2)).toUpperCase();
  }
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/** Motif 5: driver avatar slot. A consented photo URL if the hub has one, else initials on the rig colour stripe. */
export function Avatar({ name, photoUrl = null, className = "" }: { name: string; photoUrl?: string | null;
                                                                    className?: string }) {
  return (
    <span className={`avatar ${className}`} aria-hidden="true">
      {photoUrl ? <img src={photoUrl} alt="" /> : <span className="avatar__initials">{initials(name)}</span>}
    </span>
  );
}

/**
 * Motif 6: huge wide words in rows, alternating filled and outlined, sliding sideways in opposite
 * directions. Only for moments, view wipes and attract mode, never next to live data.
 */
export function KineticType({ words, rows = 3, className = "" }: { words: string[]; rows?: number; className?: string }) {
  const line = Array.from({ length: 4 }, () => words).flat();
  return (
    <div className={`kinetic ${className}`} aria-hidden="true">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className={`kinetic__row kinetic__row--${r % 2 ? "rev" : "fwd"}`}>
          {line.map((w, i) => (
            <span key={i} className={(i + r) % 2 ? "kinetic__word kinetic__word--outline" : "kinetic__word"}>{w}</span>
          ))}
        </div>
      ))}
    </div>
  );
}
