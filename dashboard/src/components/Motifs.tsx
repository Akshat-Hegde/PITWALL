// The design motifs from docs/DESIGN.md §2, drawn in SVG/CSS. Nothing here is taken from a reference file.

type Corner = "top-right" | "bottom-left" | "top-left" | "bottom-right";

/**
 * Motif 1: five parallel lines that run in from a screen edge, bend 45° with a rounded corner and leave
 * through the top edge, fading out where they enter. Drawn for the top-left; other corners mirror it in CSS.
 * One per view, in the empty title row; aria-hidden decoration.
 */
export function StripeBundle({ corner = "top-right", className = "" }: { corner?: Corner; className?: string }) {
  // Drawn for the top-left corner; CSS mirrors it into the other corners. Bold slanted blocks over a halftone
  // dot field that fades away from the corner (our own drawing, racing-poster style).
  const id = `halftone-${corner}`;
  return (
    <svg className={`stripes stripes--${corner} ${className}`} viewBox="0 0 440 330" aria-hidden="true">
      <defs>
        <pattern id={`${id}-dots`} width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <circle cx="4.5" cy="4.5" r="1.6" fill="currentColor" />
        </pattern>
        <radialGradient id={`${id}-fade`} cx="0" cy="0" r="1" gradientUnits="objectBoundingBox">
          <stop offset="0" stopColor="#fff" stopOpacity="0.9" />
          <stop offset="0.75" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id={`${id}-mask`}>
          <rect width="440" height="330" fill={`url(#${id}-fade)`} />
        </mask>
      </defs>
      <rect className="stripes__dots" width="440" height="330" fill={`url(#${id}-dots)`} mask={`url(#${id}-mask)`} />
      <path className="stripes__block" d="M118 0 L196 0 L0 236 L0 142 Z" />
      <path className="stripes__block stripes__block--thin" d="M236 0 L262 0 L44 262 L18 262 Z" />
      <path className="stripes__block stripes__block--short" d="M300 0 L334 0 L254 96 L220 96 Z" />
    </svg>
  );
}

/** The same motif small, for the header band of the TV pages: three slanted blocks and a few dots. */
export function SlashMark({ className = "" }: { className?: string }) {
  return (
    <svg className={`slashmark ${className}`} viewBox="0 0 120 52" preserveAspectRatio="xMaxYMid meet" aria-hidden="true">
      <defs>
        <pattern id="slash-dots" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <circle cx="3" cy="3" r="1.1" fill="currentColor" />
        </pattern>
      </defs>
      <rect className="slashmark__dots" x="0" width="70" height="52" fill="url(#slash-dots)" />
      <path className="stripes__block" d="M78 0 L98 0 L74 52 L54 52 Z" />
      <path className="stripes__block stripes__block--thin" d="M104 0 L112 0 L88 52 L80 52 Z" />
      <path className="stripes__block" d="M116 0 L120 0 L120 52 L96 52 Z" />
    </svg>
  );
}

/**
 * Stepped speed bars: horizontal bars, red and navy, whose free ends step along a diagonal and are cut on the
 * slant, like a livery flash. `from` is the edge the bars grow out of.
 */
export function SpeedSteps({ width, height, bars = 12, from = "left", className = "" }: {
  width: number; height: number; bars?: number; from?: "left" | "right"; className?: string;
}) {
  const pitch = height / bars;
  const thick = pitch * 0.55;
  const slant = thick * 0.9;
  return (
    <svg className={`speedsteps ${className}`} viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
      <g transform={from === "right" ? `translate(${width} 0) scale(-1 1)` : undefined}>
        {Array.from({ length: bars }, (_, i) => {
          const y = i * pitch;
          const len = Math.max(slant + 2, width * (0.25 + (0.75 * (i + 1)) / bars) - (i % 3 === 1 ? width * 0.18 : 0));
          const navy = i % 2 === 1;
          return (
            <path key={i} d={`M0 ${y} H${len} L${len - slant} ${y + thick} H0 Z`}
                  fill={navy ? "#22324D" : "var(--brand-accent, #E10600)"} opacity={navy ? 1 : 1 - (bars - 1 - i) * 0.03} />
          );
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
