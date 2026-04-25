import * as path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "src/shared"),
      "@renderer": path.resolve(__dirname, "src/renderer")
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/renderer/test/setup.ts"]
  }
});
