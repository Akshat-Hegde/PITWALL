// Brand: our own mark (a slanted red "P" with a chequered-flag strip fading out beside it, like a flag
// streaking past) and the wordmark (the product name from brand.py, split in two colours). Drawn by us; nothing taken from any motorsport mark.

/** The P: stem and bowl in one slanted outline, counter cut out (even-odd). */
export const PITWALL_P = "M14 0 H33 C38.5 0 40.6 3.6 39.4 8.2 L38.4 12 C37.2 16.6 33.8 19 28.6 19 H19.9 L17.4 28 H8.6 Z M22.8 6.4 L21.6 12.4 H28.4 C30.1 12.4 31 11.6 31.4 10.2 L31.8 8.6 C32.2 7.2 31.6 6.4 30 6.4 Z";

/** The chequered strip beside the P: white squares, fading out to the left (x, y, opacity), 3 units each. */
export const PITWALL_CHEQUER: [number, number, number][] = [[3.8, 8, 0.84], [-2.2, 8, 0.52], [-8.2, 8, 0.2], [6.8, 11, 1.0], [0.8, 11, 0.68], [-5.2, 11, 0.36], [3.8, 14, 0.84], [-2.2, 14, 0.52], [-8.2, 14, 0.2], [6.8, 17, 1.0], [0.8, 17, 0.68], [-5.2, 17, 0.36]];

function Mark() {
  return (
    <>
      <g transform="translate(0 14) skewX(-10.9) translate(0 -14)">
        {PITWALL_CHEQUER.map(([x, y, o], i) => <rect key={i} x={x} y={y} width={3} height={3} fill="#fff" opacity={o} />)}
      </g>
      <path d={PITWALL_P} fill="#E10600" fillRule="evenodd" />
    </>
  );
}

/** The mark alone. */
export function PitwallMark({ className = "", size = 28 }: { className?: string; size?: number }) {
  return (
    <svg className={`pwmark ${className}`} viewBox="-11 0 52 28" width={(size * 52) / 28} height={size} aria-hidden="true">
      <Mark />
    </svg>
  );
}

/** Mark + wordmark (first half of the name white, second half red), on one line. */
export function PitwallLogo({ className = "", height = 22 }: { className?: string; height?: number }) {
  const word = __PRODUCT_NAME__.toUpperCase();
  const cut = Math.floor(word.length / 2);
  return (
    <svg className={`pwlogo ${className}`} viewBox="-11 0 205 28" height={height} width={(height * 205) / 28}
         role="img" aria-label={__PRODUCT_NAME__}>
      <Mark />
      <text x="50" y="24.5" className="pwlogo__word" fill="#fff">
        {word.slice(0, cut)}<tspan fill="#E10600">{word.slice(cut)}</tspan>
      </text>
    </svg>
  );
}
