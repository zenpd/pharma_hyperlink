import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for the hyperlink-engine dashboard.
//
// The dev server proxies /api requests to the FastAPI backend so the
// React app can talk to the real engine without CORS plumbing.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
