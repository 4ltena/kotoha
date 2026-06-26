import { defineConfig } from "vitest/config";

// Separate vitest config so the test root is overlay/ (not renderer/).
// vite.config.js sets root:"renderer" for the Vite dev server; vitest needs its own root.
export default defineConfig({
  test: {
    include: ["test/**/*.test.js"],
  },
});
