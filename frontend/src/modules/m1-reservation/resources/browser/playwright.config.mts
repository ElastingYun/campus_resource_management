import { defineConfig, devices } from "@playwright/test";
import process from "node:process";
import { resolve } from "node:path";
const origin = process.env.B_RESOURCE_BROWSER_ORIGIN;
if (!origin || !/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))
  throw new Error(
    "B browser acceptance requires the isolated loopback launcher",
  );
const channel = process.env.B_RESOURCE_BROWSER_CHANNEL;
const sharedHost = process.env.B_RESOURCE_HOST_ACCEPTANCE === "1";
if (channel && channel !== "chrome")
  throw new Error("Unsupported browser channel");
export default defineConfig({
  testDir: ".",
  testMatch: sharedHost ? "resources-host.spec.ts" : "resources.spec.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: true,
  timeout: 45000,
  globalTimeout: 240000,
  reporter: "list",
  outputDir: resolve(
    process.cwd(),
    sharedHost ? "test-results/b-resource-host" : "test-results/b-resources",
  ),
  use: {
    baseURL: origin,
    browserName: "chromium",
    channel,
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
