/// <reference types="vitest" />
import { defineConfig } from "vitest/config";

export default defineConfig({
  server: {
    // Explicit rather than the default `localhost`, which on macOS resolves to
    // ::1 first and leaves anything polling 127.0.0.1 -- Playwright's webServer
    // check, for one -- waiting on a port nothing is listening on.
    host: "127.0.0.1",
    port: 5173,
    // The Python side owns /api and serves the repo's kits/ directory at /kits
    // (see the StaticFiles mount in bolbox/server.py). Proxying both instead of
    // hardcoding an origin keeps the app same-origin in dev, so nothing here
    // depends on the server's CORS list staying in sync with this port.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/kits": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
