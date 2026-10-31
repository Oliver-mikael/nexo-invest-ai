/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f6f5f0",
        ink: {
          900: "#0d1215",
          800: "#161e22",
          700: "#22303a",
          500: "#4b5c66",
          300: "#8a9aa3",
        },
        moss: {
          600: "#0b6b53",
          500: "#0f8466",
          100: "#e2f1ec",
        },
        amber: {
          600: "#a86413",
          500: "#c67b1b",
          100: "#f8eddb",
        },
        rust: { 600: "#a33a2a", 100: "#f7e4e0" },
      },
      fontFamily: {
        display: ['"Instrument Serif"', "Georgia", "serif"],
        sans: ['"Inter"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(13,18,21,0.06), 0 8px 24px -16px rgba(13,18,21,0.35)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        rise: "rise 0.45s ease-out both",
        pulseSoft: "pulseSoft 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
}
