import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vitest/config";

// The product name is defined once, in hub/simtelemetry/brand.py. Read it at build time.
function readProductName(): string {
  const file = fileURLToPath(new URL("../hub/simtelemetry/brand.py", import.meta.url));
  const match = /^PRODUCT_NAME\s*=\s*["']([^"']+)["']/m.exec(readFileSync(file, "utf-8"));
  if (!match || !match[1]) throw new Error(`PRODUCT_NAME not found in ${file}; the dashboard build needs it.`);
  return match[1];
}
const PRODUCT_NAME = readProductName();

// Fills the name into index.html (the <title> and anything else that says %PRODUCT_NAME%).
const productNameHtml = (): Plugin => ({
  name: "product-name-html",
  transformIndexHtml: (html) => html.replaceAll("%PRODUCT_NAME%", PRODUCT_NAME),
});

// In production the hub serves the built files itself (same origin as /ws and /api).
// In dev, ?source=ws talks to a hub on localhost:8000 through this proxy.
export default defineConfig({
  plugins: [react(), productNameHtml()],
  define: { __PRODUCT_NAME__: JSON.stringify(PRODUCT_NAME) },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
