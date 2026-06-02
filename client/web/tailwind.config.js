/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef2ff",
          100: "#dce2fd",
          200: "#b9c6fb",
          300: "#8ba3f7",
          400: "#5b7bf2",
          500: "#3370ff",
          600: "#2556d6",
          700: "#1c44b0",
          800: "#19358c",
          900: "#152a6e",
        },
        accent: {
          green:  "#22c55e",
          orange: "#f97316",
          purple: "#8b5cf6",
          pink:   "#ec4899",
          teal:   "#06b6d4",
          amber:  "#f59e0b",
          rose:   "#f43f5e",
          indigo: "#6366f1",
        },
        surface: {
          white:  "#ffffff",
          light:  "#f5f6f8",
          gray:   "#e8eaed",
          border: "#d4d7dc",
          muted:  "#8f959e",
          dark:   "#1f2329",
          darker: "#191c21",
          black:  "#0f1114",
        },
      },
      fontSize: { xxs: ["11px", "16px"] },
      boxShadow: {
        'glow': '0 0 40px -10px rgba(51,112,255,0.3)',
        'glow-purple': '0 0 40px -10px rgba(139,92,246,0.3)',
        'card': '0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)',
        'card-hover': '0 4px 24px -4px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)',
      },
    },
  },
  plugins: [],
};
