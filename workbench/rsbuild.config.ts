import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

const basePath = process.env.BASE_PATH || "";

export default defineConfig({
  plugins: [pluginReact()],
  server: {
    port: 3000,
    proxy: {
      "/auth": {
        target: "http://127.0.0.1:8801",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:8801",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8801",
        changeOrigin: true,
      },
    },
  },
  output: {
    assetPrefix: basePath ? `${basePath}/` : "/",
  },
  source: {
    define: {
      __BASE_PATH__: JSON.stringify(basePath),
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
