import Link from "next/link";
import { ArrowLeft, Receipt, Search } from "lucide-react";

// Reachable two ways: a typo'd route, or a real invoice ID that doesn't
// exist (invoices/[invoiceId]/page.tsx calls next/navigation's notFound()
// on a 404 from the API). Rendered inside the root layout, so it still
// picks up SiteChrome's console sidebar/landing nav depending on the URL
// that led here -- no special-casing needed here for that.
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center py-16 text-center">
      <span className="label !text-text-faint">404</span>
      <h1 className="font-display mt-3 text-3xl font-semibold tracking-tight text-text">Nothing here.</h1>
      <p className="mt-2 max-w-sm text-sm text-text-muted">
        This invoice or page doesn&apos;t exist in the live pool — check the invoice number, or head back to a known
        page.
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/invoices"
          className="flex items-center gap-2 rounded-[var(--radius-control)] border border-accent/40 bg-accent-soft px-4 py-2 text-sm font-medium text-accent-text transition-colors hover:bg-accent-soft/70"
        >
          <Receipt size={15} /> Browse invoices
        </Link>
        <Link
          href="/"
          className="flex items-center gap-2 rounded-[var(--radius-control)] border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:border-border-strong hover:text-text"
        >
          <ArrowLeft size={15} /> Back to landing
        </Link>
      </div>
      <p className="mt-8 flex items-center gap-1.5 text-xs text-text-faint">
        <Search size={12} /> Looking for a specific demo case? Use the menu in the sidebar.
      </p>
    </div>
  );
}
