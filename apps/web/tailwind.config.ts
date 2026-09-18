// ============================================================================
// Academic Edge web - Tailwind CSS 3 configuration.
//
// README (web app): see apps/web/README.md
//
// Design rules encoded here:
//  * `darkMode: "class"` - one `dark` class on <html>, flipped by
//    src/components/ThemeToggle.tsx and applied pre-paint by the bootstrap
//    script in src/lib/theme.ts (no flash of the wrong theme).
//  * Semantic colour tokens only (surface/ink/line/accent/positive/caution/
//    danger). Analysts read long tables, so contrast is deliberate in both
//    themes and numbers use tabular figures.
//  * No decorative gambling imagery: there is no asset pipeline here at all,
//    only typography, borders and inline SVG.
// ============================================================================

import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "rgb(var(--ae-surface) / <alpha-value>)",
          raised: "rgb(var(--ae-surface-raised) / <alpha-value>)",
          sunken: "rgb(var(--ae-surface-sunken) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ae-ink) / <alpha-value>)",
          muted: "rgb(var(--ae-ink-muted) / <alpha-value>)",
          subtle: "rgb(var(--ae-ink-subtle) / <alpha-value>)",
        },
        line: "rgb(var(--ae-line) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--ae-accent) / <alpha-value>)",
          soft: "rgb(var(--ae-accent-soft) / <alpha-value>)",
        },
        positive: {
          DEFAULT: "rgb(var(--ae-positive) / <alpha-value>)",
          soft: "rgb(var(--ae-positive-soft) / <alpha-value>)",
        },
        caution: {
          DEFAULT: "rgb(var(--ae-caution) / <alpha-value>)",
          soft: "rgb(var(--ae-caution-soft) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--ae-danger) / <alpha-value>)",
          soft: "rgb(var(--ae-danger-soft) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      keyframes: {
        "ae-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        "ae-pulse": "ae-pulse 1.8s ease-in-out infinite",
      },
      screens: {
        xs: "420px",
      },
    },
  },
  plugins: [],
};

export default config;
