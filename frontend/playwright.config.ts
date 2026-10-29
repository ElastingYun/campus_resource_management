import { defineConfig, devices } from "@playwright/test";
const origin = process.env.CAMPUS_M2_LIVE_ORIGIN;
if (process.env.CI === "true" && !origin)
  throw new Error("Real M2 acceptance origin required in CI");
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 60000,
  globalTimeout: 180000,
  reporter: process.env.CI ? [["github"], ["line"]] : "list",
  use: {
    baseURL: origin ?? "http://127.0.0.1:5173",
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], defaultBrowserType: "chromium" },
    },
  ],
});
