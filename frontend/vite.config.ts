import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Folder of the project's .env file, found by walking up from here (as the Python side does). */
function envDir(): string | undefined {
  let dir = dirname(fileURLToPath(import.meta.url));
  while (!existsSync(join(dir, ".env"))) {
    const parent = dirname(dir);
    if (parent === dir) return undefined;
    dir = parent;
  }
  return dir;
}

// In development the interface runs on Vite's port and forwards API calls to
// the Python server, on the PORT set in the .env file; in production server.py
// serves the built files itself.
export default defineConfig(({ command, mode }) => {
  const dir = envDir();
  const apiPort = dir ? loadEnv(mode, dir, "").PORT : undefined;
  if (command === "serve" && !apiPort) {
    throw new Error("PORT is not set yet. Run python server.py once: it writes PORT to the .env file.");
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: apiPort ? { "/api": `http://localhost:${apiPort}` } : undefined,
    },
    build: { outDir: "dist", emptyOutDir: true },
  };
});
