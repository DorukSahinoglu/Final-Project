import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#060816",
        foreground: "#eef4ff",
        surface: "#0b1020",
        "surface-2": "#10172b",
        accent: "#57e6ff",
        "accent-2": "#8895ff",
        success: "#55efc4",
        warning: "#ffd166",
        danger: "#ff7a90",
        border: "rgba(255,255,255,0.08)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(87,230,255,0.08), 0 12px 50px rgba(35,207,255,0.14)",
        panel: "0 24px 80px rgba(0,0,0,0.42)",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
      },
      animation: {
        float: "float 9s ease-in-out infinite",
        pulseGlow: "pulseGlow 3.5s ease-in-out infinite",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-10px)" },
        },
        pulseGlow: {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
