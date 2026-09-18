import type { Metadata, Viewport } from "next";

import "./globals.css";
import { AppProviders } from "./providers";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Academic Edge — market intelligence",
  description:
    "Read-only football market intelligence: canonical events, cross-venue price comparison, arbitrage and model-vs-market expected value with full evidence. No wagering.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
};

/**
 * Root layout. The theme bootstrap script runs before paint so a dark-mode
 * analyst never sees a white flash; everything else is server-rendered chrome.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body>
        <AppProviders>
          <div className="flex min-h-screen flex-col">
            <SiteHeader />
            <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6">{children}</main>
            <SiteFooter />
          </div>
        </AppProviders>
      </body>
    </html>
  );
}

function SiteHeader() {
  const links: Array<{ href: string; label: string }> = [
    { href: "/", label: "Opportunities" },
    { href: "/sources", label: "Sources" },
    { href: "/resolver", label: "Resolver" },
    { href: "/predictions", label: "Models" },
    { href: "/alerts", label: "Alerts" },
    { href: "/ledger", label: "Paper ledger" },
  ];
  return (
    <header className="border-b border-line bg-surface-raised">
      <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tracking-tight">Academic Edge</span>
          <span className="chip">read-only</span>
        </div>
        <nav aria-label="Sections" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {links.map((link) => (
            <a key={link.href} href={link.href} className="text-ink-muted hover:text-ink hover:underline">
              {link.label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-line bg-surface-raised">
      <div className="mx-auto w-full max-w-[1400px] px-4 py-3 text-2xs text-ink-muted">
        Research tooling only. Academic Edge never places bets, never signs wallets and never
        stores bookmaker credentials. Every number is shown with its source, timestamp and
        freshness so you can judge it yourself.
      </div>
    </footer>
  );
}
