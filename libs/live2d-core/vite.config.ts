import { resolve } from "path";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

export default defineConfig({
  plugins: [dts({ rollupTypes: true })],
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      name: "Live2DCore",
      formats: ["umd", "es"],
      fileName: (format) =>
        format === "es" ? "live2d-core.mjs" : "live2d-core.js",
    },
    rollupOptions: {
      // Externalize pixi.js so consumers can use their own version
      external: ["pixi.js"],
      output: {
        globals: {
          "pixi.js": "PIXI",
        },
      },
    },
    minify: "esbuild",
    target: "es2022",
  },
});
