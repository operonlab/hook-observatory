import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "path";

export default defineConfig({
  base: "./",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        globPatterns: ["**/*.{js,css,html,woff2,png}"],
        importScripts: ["./push-handler.js"],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/api\.open-meteo\.com\/.*/i,
            handler: "StaleWhileRevalidate",
            options: {
              cacheName: "open-meteo-cache",
              expiration: { maxAgeSeconds: 30 * 60 },
            },
          },
        ],
      },
      manifest: {
        name: "Agent Vista",
        short_name: "AgentVista",
        description: "Pixel-art virtual office for local LLM CLI agents",
        theme_color: "#1a1a2e",
        background_color: "#1a1a2e",
        display: "standalone",
        orientation: "any",
        icons: [
          { src: "./icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "./icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "./icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:10207",
      "/ws": {
        target: "ws://localhost:10207",
        ws: true,
      },
    },
  },
});
