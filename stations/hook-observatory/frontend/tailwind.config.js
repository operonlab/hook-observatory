/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "#0a0a0e",
          1: "#12121a",
          2: "#1a1b2e",
          3: "#222338",
        },
        accent: "#89b4fa",
      },
    },
  },
  plugins: [],
};
