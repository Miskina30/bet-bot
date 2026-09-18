// ============================================================================
// Academic Edge web (analyst dashboard) - Next.js 15 App Router configuration.
//
// README (web app): see apps/web/README.md
//
// Contract notes for this file:
//  * `output: "standalone"` produces the minimal server bundle that
//    infra/docker/web.Dockerfile copies into the runtime stage.
//  * `typescript.ignoreBuildErrors` stays FALSE: a type error must fail the
//    build. ESLint is disabled during the build only because `npm run lint`
//    runs it separately (and CI lints too); this keeps the Docker build from
//    failing solely on lint-rule drift.
//  * No external image domains and no analytics: the dashboard renders text,
//    tables and inline SVG only. There is no gambling imagery anywhere and no
//    third-party request path out of the browser.
//  * Security headers are set conservatively. The browser talks to the FastAPI
//    backend through NEXT_PUBLIC_API_BASE_URL, so `connect-src` must allow it;
//    `frame-ancestors 'none'` prevents clickjacking of analyst views.
// ============================================================================

import type { NextConfig } from "next";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next.js injects inline bootstrap scripts; our theme bootstrap script is
      // inline by design (it must run before first paint to avoid a theme flash).
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      `connect-src 'self' ${apiBaseUrl}`,
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    // The dashboard ships no photographic imagery at all; keep optimisation off
    // so no image service is ever reachable.
    unoptimized: true,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
