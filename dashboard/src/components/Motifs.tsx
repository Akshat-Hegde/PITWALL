// The design motifs from docs/DESIGN.md §2, drawn in SVG/CSS. Nothing here is taken from a reference file.

type Corner = "top-right" | "bottom-left" | "top-left" | "bottom-right";

/**
 * Motif 1: five parallel lines that run in from a screen edge, bend 45° with a rounded corner and leave
 * through the top edge, fading out where they enter. Drawn for the top-left; other corners mirror it in CSS.
 * One per view, in the empty title row; aria-hidden decoration.
 */
export function StripeBundle({ corner = "top-right", className = "" }: { corner?: Corner; className?: string }) {
  const id = `stripe-fade-${corner}`;
  return (
    <svg className={`stripes stripes--${corner} ${className}`} viewBox="0 0 440 110" aria-hidden="true">
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="260" y2="0">
          <stop offset="0" stopColor="currentColor" stopOpacity="0" />
          <stop offset="1" stopColor="currentColor" stopOpacity="1" />
        </linearGradient>
      </defs>
      {[0, 1, 2, 3, 4].map((i) => {
        const y = 46 + i * 14; // horizontal run, then a rounded 45° bend up and out of the top edge
        const x = 250 + i * 14 * 0.414;
        const r = 18;
        return (
          <path key={i} stroke={`url(#${id})`}
                d={`M0 ${y} L${x} ${y} Q${x + r} ${y} ${x + r * 1.7} ${y - r * 0.7} L${x + r * 1.7 + y} ${-r * 0.7 - 2}`} />
        );
      })}
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
