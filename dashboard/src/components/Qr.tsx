import qrcode from "qrcode-generator";

/** QR code as crisp SVG squares (generated in the browser, no network). */
export function Qr({ text, className = "", label }: { text: string; className?: string;
  /** Accessible name; defaults to the encoded text. Pass one for a QR that holds a secret (Wi-Fi password). */
  label?: string }) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const cells: string[] = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) if (qr.isDark(r, c)) cells.push(`M${c + 2} ${r + 2}h1v1h-1z`);
  }
  return (
    <svg className={`qr ${className}`} viewBox={`0 0 ${n + 4} ${n + 4}`} role="img" aria-label={label ?? `QR code: ${text}`}
         shapeRendering="crispEdges">
      <rect width={n + 4} height={n + 4} fill="#fff" />
      <path d={cells.join("")} fill="#000" />
    </svg>
  );
}

/** The cafe's "Join our Wi-Fi" QR code. The encoded text holds the password: it never appears as text. */
export function WifiQr({ wifi, className = "" }: { wifi: { ssid: string; qr: string }; className?: string }) {
  return <Qr text={wifi.qr} className={className} label={`Wi-Fi QR code: ${wifi.ssid}`} />;
}
