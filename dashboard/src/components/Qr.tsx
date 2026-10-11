import qrcode from "qrcode-generator";

/** QR code as crisp SVG squares (generated in the browser, no network). */
export function Qr({ text, className = "" }: { text: string; className?: string }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const cells: string[] = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) if (qr.isDark(r, c)) cells.push(`M${c + 2} ${r + 2}h1v1h-1z`);
  }
  return (
    <svg className={`qr ${className}`} viewBox={`0 0 ${n + 4} ${n + 4}`} role="img" aria-label={`QR code: ${text}`}
         shapeRendering="crispEdges">
      <rect width={n + 4} height={n + 4} fill="#fff" />
      <path d={cells.join("")} fill="#000" />
    </svg>
  );
}
