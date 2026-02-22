import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

export default defineConfig({
  plugins: [pluginReact()],
  server: {
    port: 3000,
    proxy: {
      "/auth": {
        target: "http://127.0.0.1:8800",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:8800",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8800",
        changeOrigin: true,
      },
    },
  },
  html: {
    template: "./src/index.html",
  },
  resolve: {
    alias: {
      "@": "./src",
    },
  },
});
