import type { Metadata } from "next";
import Link from "next/link";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { getDemoFixtures } from "@/lib/api";
import { DemoFixture } from "@/lib/types";
import DemoCaseMenu from "./DemoCaseMenu";
import NavLinks from "./NavLinks";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans-loaded", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono-loaded", display: "swap" });

export const metadata: Metadata = {
  title: "Receivables Intelligence",
  description: "Decision engine for overdue B2B invoices -- predicts, retrieves, decides, acts, and measures.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The demo-case menu is a convenience, not core navigation -- never let a
  // backend hiccup break every page's layout. Falls back to an empty list
  // (DemoCaseMenu still renders its two filter-based links regardless).
  let fixtures: DemoFixture[] = [];
  try {
    fixtures = await getDemoFixtures();
  } catch {
    fixtures = [];
  }

  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <header className="sticky top-0 z-40 border-b border-border/80 bg-bg/75 backdrop-blur-md">
          <nav className="mx-auto flex max-w-7xl items-center gap-6 px-5 py-3.5 sm:px-8">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-text">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-[11px] font-bold text-white">
                R
              </span>
              <span className="hidden sm:inline">Receivables Intelligence</span>
            </Link>
            <div className="h-4 w-px bg-border" />
            <NavLinks />
            <div className="ml-auto">
              <DemoCaseMenu fixtures={fixtures} />
            </div>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8">{children}</main>
        <footer className="border-t border-border/60 px-5 py-6 text-center text-xs text-text-faint sm:px-8">
          Built for Razorpay AI Buildathon 2026 · Track 03 (AI Revenue Recovery) · every decision on this
          console is real, deterministic, and reproducible from persisted state.
        </footer>
      </body>
    </html>
  );
}
