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
        gold: "#e2b714",
        track: {
          img: "rgba(76,175,80,0.6)",
          card: "rgba(33,150,243,0.6)",
        },
      },
    },
  },
  plugins: [],
};
