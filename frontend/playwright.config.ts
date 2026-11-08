import { defineConfig, devices } from "@playwright/test";

// End-to-end tests in WebKit (the engine of Safari on iPhone) against a running server started
// with AI_PROVIDER=demo, so every run gets the same AI answers. See README, "Tests".
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: 2,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    // The offline worker would answer some requests itself and hide them from route mocks.
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "iphone", use: { ...devices["iPhone 15"] } }],
});
