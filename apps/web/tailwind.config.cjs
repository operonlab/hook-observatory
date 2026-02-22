/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{tsx,ts,jsx,js}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ctp: {
          base: "var(--base)",
          mantle: "var(--mantle)",
          crust: "var(--crust)",
          surface0: "var(--surface0)",
          surface1: "var(--surface1)",
          text: "var(--text)",
          subtext0: "var(--subtext0)",
          blue: "var(--blue)",
          lavender: "var(--lavender)",
          mauve: "var(--mauve)",
          green: "var(--green)",
          red: "var(--red)",
          peach: "var(--peach)",
          yellow: "var(--yellow)",
          teal: "var(--teal)",
          sky: "var(--sky)",
        },
      },
      screens: {
        sm: "640px",
        md: "768px",
        lg: "1024px",
        xl: "1280px",
      },
    },
  },
  plugins: [],
};
