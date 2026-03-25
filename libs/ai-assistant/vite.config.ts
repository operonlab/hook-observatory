import { resolve } from "path";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

export default defineConfig({
  plugins: [dts({ rollupTypes: true })],
  build: {
    lib: {
      entry: resolve(__dirname, "src/ai-assistant.ts"),
      name: "AiAssistant",
      formats: ["umd", "es"],
      fileName: (format) =>
        format === "es" ? "ai-assistant.mjs" : "ai-assistant.js",
    },
    minify: "esbuild",
    target: "es2022",
  },
});
