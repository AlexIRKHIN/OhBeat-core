import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The SPA calls /v1/... on its own origin; Vite forwards these requests to Core API.
// So the browser needs no CORS for the API, and the client IP reaches the API in X-Forwarded-For.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: apiTarget, changeOrigin: true, xfwd: true },
    },
    watch: { usePolling: process.env.CHOKIDAR_USEPOLLING === "true" },
  },
  // NFR-15: Safari 15+, Chrome 100+, Firefox 100+
  build: { target: ["safari15", "chrome100", "firefox100"] },
  test: { environment: "jsdom" },
});
