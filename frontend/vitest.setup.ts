import "@testing-library/jest-dom/vitest";

// jsdom has no `ResizeObserver` -- `recharts`' `ResponsiveContainer`
// (used by the operations dashboard's sparkline/trend tiles, frontend
// phase-04) needs one to mount. A minimal no-op stub is enough for
// component tests, which only assert on rendered text/links, not layout.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
