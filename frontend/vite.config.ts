import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the interface runs on Vite's port and forwards API calls to
// the Python server; in production server.py serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
