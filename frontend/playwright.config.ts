// End-to-end test of the whole path (ADR 0005: Playwright, Chromium and WebKit for Safari, NFR-15).
// Runs in its own container:  docker compose --profile e2e run --rm e2e
import { defineConfig, devices } from "@playwright/test";

const viewport = { width: 1366, height: 900 }; // the full menu is shown from 1280 px

export default defineConfig({
  testDir: "./e2e",
  timeout: 8 * 60_000, // Media Worker and the payment take real time
  expect: { timeout: 20_000 },
  workers: 1, // the browsers go one after another: one Media Worker serves both
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  // localhost:5173 / :9000 / :8100 inside the container lead to the services, as in your browser
  globalSetup: "./e2e/proxy.ts",
  use: {
    baseURL: "http://localhost:5173",
    locale: "ru-RU",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport } },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport } },
  ],
});
