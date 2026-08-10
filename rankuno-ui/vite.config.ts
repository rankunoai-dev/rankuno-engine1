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
});
