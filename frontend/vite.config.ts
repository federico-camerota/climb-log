// SPDX-License-Identifier: GPL-3.0-or-later
/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend started by `climblog serve` (see backend/climblog/cli.py).
const API_TARGET = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    // Inside the Python package, so FastAPI can serve it wherever the package is installed (D-039).
    outDir: "../backend/climblog/static",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: { "/api": API_TARGET },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
