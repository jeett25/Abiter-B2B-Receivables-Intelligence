import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { getDemoFixtures } from "@/lib/api";
import { DemoFixture } from "@/lib/types";
import SiteChrome from "./SiteChrome";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans-loaded", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono-loaded", display: "swap" });
const displayFont = Space_Grotesk({ subsets: ["latin"], variable: "--font-display-loaded", display: "swap" });

export const metadata: Metadata = {
  title: "Arbiter",
  description: "A deterministic decision engine for overdue B2B invoices -- predicts, retrieves, decides, acts, and measures.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The demo-case menu is a convenience, not core navigation -- never let a
  // backend hiccup break every page's layout. Falls back to an empty list
  // (SiteChrome/ConsoleSidebar still render their filter-based links
  // regardless). Chrome selection itself (landing top nav vs. console
  // sidebar) lives in SiteChrome, a Client Component, since it needs
  // usePathname() -- this layout stays a Server Component just to do this
  // fetch once and hand the result down.
  let fixtures: DemoFixture[] = [];
  try {
    fixtures = await getDemoFixtures();
  } catch {
    fixtures = [];
  }

  return (
    <html lang="en" className={`${inter.variable} ${mono.variable} ${displayFont.variable}`}>
      <body>
        <div aria-hidden className="grain" />
        <div aria-hidden className="ambient-wash" />
        <SiteChrome fixtures={fixtures}>{children}</SiteChrome>
      </body>
    </html>
  );
}
