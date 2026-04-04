/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./index.html"],
  theme: {
    extend: {
      colors: {
        dark: "#0a0a12",
        surface: "#1e1e2e",
        mocha: {
          blue: "#89b4fa",
          green: "#a6e3a1",
          red: "#f38ba8",
          yellow: "#f9e2af",
          mauve: "#cba6f7",
          text: "#cdd6f4",
          subtext: "#a6adc8",
          overlay: "#313244",
        },
      },
      borderRadius: {
        xl: "12px",
      },
      fontFamily: {
        inter: ["Inter", "system-ui", "sans-serif"],
      },
      animation: {
        "glow-pulse": "glow-pulse 3s infinite ease-in-out",
        "indicator-pulse": "indicator-pulse 2s infinite ease-in-out",
      },
      keyframes: {
        "glow-pulse": {
          "0%, 100%": { opacity: 0.8, filter: "drop-shadow(0 0 10px rgba(137, 180, 250, 0.4))" },
          "50%": { opacity: 1, filter: "drop-shadow(0 0 25px rgba(137, 180, 250, 0.8))" },
        },
        "indicator-pulse": {
          "0%": { transform: "scale(0.95)", opacity: 1 },
          "70%": { transform: "scale(1.1)", opacity: 0.5 },
          "100%": { transform: "scale(0.95)", opacity: 1 },
        },
      },
    },
  },
  plugins: [],
};