import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: "src/renderer",
  base: "./",
  build: {
    outDir: "../../dist/renderer",
    emptyOutDir: false
  },
  server: {
    strictPort: true,
    port: 5173,
    watch: {
      usePolling: true,
      interval: 250
    }
  }
});

