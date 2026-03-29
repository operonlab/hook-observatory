import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 4111,
    proxy: {
      "/projects": "http://localhost:10206",
      "/health": "http://localhost:10206",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
