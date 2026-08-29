import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "B2B Receivables Decision Intelligence",
  description: "Day 3 frontend scaffold -- mock data, structure only",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <nav style={{ padding: "1rem", borderBottom: "1px solid #ccc" }}>
          <Link href="/invoices" style={{ marginRight: "1rem" }}>
            Invoices
          </Link>
          <Link href="/metrics">Metrics</Link>
        </nav>
        <main style={{ padding: "1rem" }}>{children}</main>
      </body>
    </html>
  );
}
