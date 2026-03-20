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
  performance: {
    chunkSplit: {
      strategy: 'split-by-experience',
      override: {
        cacheGroups: {
          three: {
            test: /[\\/]node_modules[\\/](three|3d-force-graph)[\\/]/,
            name: 'three',
            chunks: 'all',
            priority: 20,
          },
          recharts: {
            test: /[\\/]node_modules[\\/](recharts|d3-[^/]+)[\\/]/,
            name: 'recharts',
            chunks: 'all',
            priority: 20,
          },
          vendor: {
            test: /[\\/]node_modules[\\/]/,
            name: 'vendor',
            chunks: 'all',
            priority: 10,
          },
        },
      },
    },
  },
});
