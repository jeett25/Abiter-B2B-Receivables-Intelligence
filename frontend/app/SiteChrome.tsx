"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { DemoFixture } from "@/lib/types";
import ConsoleBackground from "./ConsoleBackground";
import ConsoleSidebar from "./ConsoleSidebar";
import DemoCaseMenu from "./DemoCaseMenu";
import NavLinks from "./NavLinks";
import PageTransition from "./PageTransition";

// Decides which chrome renders per route (2026-09-02): the landing page
// keeps its transparent floating top nav; every console route (invoices,
// invoice detail, metrics) gets the collapsible sidebar instead. A client
// component specifically so usePathname() can make that call -- the root
// layout itself stays a Server Component (it still does the
// getDemoFixtures() fetch), this just receives the result as a prop.
export default function SiteChrome({ fixtures, children }: { fixtures: DemoFixture[]; children: ReactNode }) {
  const pathname = usePathname();
  const isLanding = pathname === "/";

  if (isLanding) {
    return (
      <>
        <header className="sticky top-0 z-40 px-5 pt-5 sm:px-8">
          <nav className="mx-auto flex max-w-7xl items-center gap-8">
            <Link href="/" className="flex items-center gap-3">
              <Image src="/logo.png" alt="Arbiter" width={34} height={34} className="shrink-0 rounded-[8px]" priority />
              <span className="hidden items-baseline gap-2 whitespace-nowrap sm:flex">
                <span className="font-display text-base font-semibold tracking-tight text-text">Arbiter</span>
                <span className="label !text-[9.5px] !tracking-[0.13em] text-text-faint">— B2B Receivables Intelligence</span>
              </span>
            </Link>
            <NavLinks />
            <div className="ml-auto">
              <DemoCaseMenu fixtures={fixtures} />
            </div>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8">
          <PageTransition>{children}</PageTransition>
        </main>
        <footer className="border-t border-border/60 px-5 py-6 text-center text-xs text-text-faint sm:px-8">
          Arbiter · a decision engine for overdue B2B invoices · every decision on this console is real,
          deterministic, and reproducible from persisted state.
        </footer>
      </>
    );
  }

  return (
    <div className="flex min-h-screen w-full">
      <ConsoleBackground />
      <ConsoleSidebar fixtures={fixtures} />
      <main className="w-full min-w-0 flex-1 px-5 py-8 sm:px-8">
        <PageTransition>{children}</PageTransition>
      </main>
    </div>
  );
}
