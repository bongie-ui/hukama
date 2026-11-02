import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Django API runs on :8000; Vite proxies /api so cookies and CSRF work same-origin.
export default defineConfig({
  plugins: [react()],
  // .env lives at the repo root (shared with Django); only VITE_* variables reach the browser.
  envDir: "..",
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  // The dashboard chunk (AG Studio) is ~1.5 MB gzipped and loads only on the dashboard page.
  build: { outDir: "dist", chunkSizeWarningLimit: 6000 },
});
