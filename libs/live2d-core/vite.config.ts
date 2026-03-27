import { resolve } from "path";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

export default defineConfig({
  plugins: [dts({ rollupTypes: true })],
  build: {
    lib: {
      entry: {
        "live2d-core": resolve(__dirname, "src/index.ts"),
        "cubism-entry": resolve(__dirname, "src/cubism-entry.ts"),
      },
      formats: ["es"],
    },
    rollupOptions: {
      external: ["pixi.js", /^untitled-pixi-live2d-engine/],
      output: {
        globals: { "pixi.js": "PIXI" },
      },
    },
    minify: "esbuild",
    target: "es2022",
  },
});
