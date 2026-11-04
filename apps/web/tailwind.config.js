/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Light theme neutrals. The scale is "surface-first": 950/900 are the lightest
        // surfaces and 50 is the darkest text, so `bg-ink-900 text-ink-100` reads as
        // white page / dark text.
        ink: {
          950: "#f6f8fa", // sidebar / drawer surface
          900: "#ffffff", // page background, inputs
          850: "#f6f8fa", // panels / cards
          800: "#eef1f5", // hover rows, secondary buttons
          700: "#e2e6ec", // borders, skeletons
          600: "#cfd5de", // input borders
          500: "#94a3b8", // very muted text
          400: "#64748b", // muted text
          300: "#475569", // secondary text
          200: "#334155",
          100: "#1e293b", // primary text
          50: "#0f172a", // headings
        },
      },
      boxShadow: {
        panel: "0 1px 2px 0 rgba(15,23,42,0.04), 0 1px 0 0 rgba(15,23,42,0.02)",
      },
    },
  },
  plugins: [],
};
