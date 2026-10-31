/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#6d28d9", dark: "#5b21b6", light: "#ede9fe" },
      },
    },
  },
  plugins: [],
};
