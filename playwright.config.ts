import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for the BeautyCare MVP.
 *
 * The backend serves the built PWA from frontend/dist on http://127.0.0.1:8000,
 * so a single server process is enough for the three required flows.
 * Start it once with:  ./scripts/run_e2e_server.sh
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "docs/evaluation/playwright-report.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } },
    },
  ],
});
