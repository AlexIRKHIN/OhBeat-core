// Neptunian palette (ADR 0009): dark graphite panels, light-cyan labels,
// blue accents (Selection / Highlight / Mute swatches), orange as the secondary accent (knob rings).
// Components use these semantic names, never raw colors, so the theme lives in one place.

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        nep: "#1b1c1e", // page background
        panel: { DEFAULT: "#222326", 2: "#18191b" }, // cards / inputs and wells
        line: "#303236", // borders and separators
        ink: "#d9eef7", // main text
        soft: "#a9c3cf", // secondary text
        muted: "#7a8f99", // hints, placeholders
        cyan: "#78d2f2", // headings, field labels, links ("Adjustments", "Text" swatch)
        accent: { DEFAULT: "#3eaaea", deep: "#2a72aa", light: "#4fbfe1" }, // Mute/Option, Highlight, Selection
        orange: "#f2a43a", // secondary accent (knob rings)
        danger: "#f06a72",
      },
      boxShadow: {
        panel: "inset 0 1px 0 rgba(255,255,255,0.03), 0 1px 2px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};
