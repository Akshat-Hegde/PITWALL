import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In production the hub serves the built files itself (same origin as /ws and /api).
// In dev, ?source=ws talks to a hub on localhost:8000 through this proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
