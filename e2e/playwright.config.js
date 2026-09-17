import { defineConfig, devices } from "@playwright/test";

/**
 * Drives the real stack, not a mock: BASE_URL is the nginx container that
 * serves the built console and proxies /api to FastAPI, so every assertion
 * here exercises the same path an operator's browser would.
 *
 * Run from the repo root with:
 *   docker compose up -d --build
 *   ./e2e/run.sh
 */
const baseURL = process.env.BASE_URL || "http://localhost:8081";

export default defineConfig({
  testDir: "./tests",
  // Serial on purpose. The suite creates a camera, starts a worker on it and
  // waits for detections; two files racing would fight over one CPU-bound
  // pipeline and over the same camera-name uniqueness constraint.
  fullyParallel: false,
  workers: 1,
  // Inference on CPU is slow: a first frame can take tens of seconds while
  // torch warms up.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["json", { outputFile: "results.json" }],
  ],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "on",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    viewport: { width: 1600, height: 1000 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
