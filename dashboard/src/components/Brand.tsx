// Pitwall brand: our own mark (a slanted "P" with two speed bars trailing it, like a pit board flashing past)
// and the PITWALL wordmark. Drawn by us; nothing taken from any motorsport mark.

/** The mark alone, 40 x 28 units. */
export const PITWALL_MARK_PATHS = [
  // speed bars
  "M0 18 H9 L7.8 21.5 H-1.2 Z",
  "M3 24 H8 L6.8 27.5 H1.8 Z",
  // the P: stem and bowl in one slanted outline, counter cut out (even-odd)
  "M14 0 H33 C38.5 0 40.6 3.6 39.4 8.2 L38.4 12 C37.2 16.6 33.8 19 28.6 19 H19.9 L17.4 28 H8.6 Z" +
    " M22.8 6.4 L21.6 12.4 H28.4 C30.1 12.4 31 11.6 31.4 10.2 L31.8 8.6 C32.2 7.2 31.6 6.4 30 6.4 Z",
];

export function PitwallMark({ className = "", size = 28 }: { className?: string; size?: number }) {
  return (
    <svg className={`pwmark ${className}`} viewBox="-2 0 44 28" width={(size * 44) / 28} height={size} aria-hidden="true">
      {PITWALL_MARK_PATHS.map((d, i) => (
        <path key={i} d={d} fill={i < 2 ? "#fff" : "#E10600"} fillRule="evenodd" opacity={i === 1 ? 0.6 : 1} />
      ))}
    </svg>
  );
}

/** Mark + wordmark ("PIT" white, "WALL" red), on one line. */
export function PitwallLogo({ className = "", height = 22 }: { className?: string; height?: number }) {
  return (
    <svg className={`pwlogo ${className}`} viewBox="-2 0 196 28" height={height} width={(height * 196) / 28}
         role="img" aria-label="Pitwall">
      {PITWALL_MARK_PATHS.map((d, i) => (
        <path key={i} d={d} fill={i < 2 ? "#fff" : "#E10600"} fillRule="evenodd" opacity={i === 1 ? 0.6 : 1} />
      ))}
      <text x="50" y="24.5" className="pwlogo__word" fill="#fff">
        PIT<tspan fill="#E10600">WALL</tspan>
      </text>
    </svg>
  );
}
