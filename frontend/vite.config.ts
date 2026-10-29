import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const backend = process.env.CAMPUS_DEV_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/health": backend,
      "/api": backend,
    },
  },
});
