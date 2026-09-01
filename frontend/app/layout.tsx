import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { getDemoFixtures } from "@/lib/api";
import { DemoFixture } from "@/lib/types";
import DemoCaseMenu from "./DemoCaseMenu";

export const metadata: Metadata = {
  title: "B2B Receivables Decision Intelligence",
  description: "Day 6 -- live backend-wired dashboard",
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
    <html lang="en">
      <body>
        <nav style={{ padding: "1rem", borderBottom: "1px solid #ccc", display: "flex", gap: "1rem" }}>
          <Link href="/invoices">Invoices</Link>
          <Link href="/metrics">Metrics</Link>
          <DemoCaseMenu fixtures={fixtures} />
        </nav>
        <main style={{ padding: "1rem" }}>{children}</main>
      </body>
    </html>
  );
}
