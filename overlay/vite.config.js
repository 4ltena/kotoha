import { defineConfig } from "vite";

// renderer/ is the web root; build emits to ../dist for Electron to load in prod.
export default defineConfig({
  root: "renderer",
  base: "./",
  build: { outDir: "../dist", emptyOutDir: true },
  server: { port: 5273 },
});
