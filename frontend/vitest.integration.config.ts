import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "node",
    include: ["integration/**/*.test.ts"],
    testTimeout: 60000,
    hookTimeout: 10000,
    fileParallelism: false,
  },
});
