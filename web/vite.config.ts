import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Behind Caddy (Compose) the API is same-origin. When running `npm run dev` directly on a
// developer machine, proxy API and admin calls to the Django dev server instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
