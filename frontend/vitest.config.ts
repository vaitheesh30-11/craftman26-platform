import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // No `@vitejs/plugin-react` is installed -- Vite's own esbuild transform
  // handles JSX, but defaults to the classic runtime (`React.createElement`
  // with no auto-import), which threw "React is not defined" the moment a
  // component test rendered JSX. `jsx: "automatic"` switches to the React
  // 17+ runtime that auto-imports `react/jsx-runtime` instead.
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
