// ============================================================================
// Academic Edge web - PostCSS pipeline.
//
// README (web app): see apps/web/README.md
//
// Tailwind CSS 3 + Autoprefixer only. No CSS-in-JS, no CSS modules and no
// component library: the dashboard uses Tailwind utilities plus the small set
// of `.panel` / `.chip` / `.btn` component classes defined in
// src/app/globals.css.
// ============================================================================

/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};

export default config;
