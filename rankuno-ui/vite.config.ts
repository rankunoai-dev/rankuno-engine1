/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: false },
  build: {
    // The 20k-page fixture is ~16 MB. Warning at the default 500 kB would fire
    // on every build and train us to ignore the one warning that matters.
    chunkSizeWarningLimit: 2000,
  },
  test: {
    // jsdom rather than a real browser. These tests exist to catch a component
    // that will not mount, a handler that is never wired, or a prop that
    // arrives undefined — none of which need a compositor, and all of which
    // `tsc` and `vite build` are blind to.
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    // Only component tests. The 16 MB synthetic fixtures live under `src/data`
    // and a glob that swept them would spend the whole budget parsing JSON.
    include: ["src/**/*.test.{ts,tsx}"],
    // Errors from a component that fails to mount are the entire point of this
    // suite, so they must not be swallowed by a reporter that only prints a
    // summary line.
    reporters: "verbose",
    pool: "forks",
    // The tests finish in about a second; Vitest then waits on file handles
    // that Vite does not release on Windows — 26 of them, per the
    // `hanging-process` reporter, with no stack trace between them. The
    // default 10-second grace period would be charged to every quality-gate
    // run for a process that has already reported its result.
    //
    // Shortened rather than "fixed": the handles are Vite's, the run has
    // already exited zero by the time this elapses, and a second is enough for
    // an orderly close when one is possible. Revisit if Vitest resolves it
    // upstream.
    teardownTimeout: 1_000,
  },
});
