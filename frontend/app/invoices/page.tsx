import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { ApiError, listInvoices } from "@/lib/api";
import { ErrorPanel, EmptyState, PageHeader } from "@/lib/ui";
import RefreshButton from "../RefreshButton";
import InvoiceFilters from "./InvoiceFilters";
import InvoiceRow from "./InvoiceRow";

// Screen 1 (master doc Day 3): overdue invoices, status, recoverability
// score, next action. Redesigned (2026-09-02) against the new console
// shell (ConsoleSidebar) -- this page now runs full-width (no max-w-7xl
// cap, that constraint lived on the old shared layout, which the console
// route group no longer uses) since a dense data table benefits from the
// extra width a centered marketing-page column doesn't need.

const PAGE_SIZE = 50;

function buildHref(
  currentState: string | undefined,
  segment: string | undefined,
  invoiceNumber: string | undefined,
  offset: number
): string {
  const params = new URLSearchParams();
  if (currentState) params.set("current_state", currentState);
  if (segment) params.set("segment", segment);
  if (invoiceNumber) params.set("invoice_number", invoiceNumber);
  if (offset > 0) params.set("offset", String(offset));
  const qs = params.toString();
  return qs ? `/invoices?${qs}` : "/invoices";
}

export default async function InvoicesPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const currentState = typeof sp.current_state === "string" && sp.current_state ? sp.current_state : undefined;
  const segment = typeof sp.segment === "string" && sp.segment ? sp.segment : undefined;
  const invoiceNumber = typeof sp.invoice_number === "string" && sp.invoice_number ? sp.invoice_number : undefined;
  const offset = Math.max(0, Number(sp.offset) || 0);
  const currentHref = buildHref(currentState, segment, invoiceNumber, offset);

  let invoices;
  try {
    invoices = await listInvoices({ currentState, segment, invoiceNumber, limit: PAGE_SIZE, offset });
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Unexpected error loading invoices.";
    return (
      <div>
        <PageHeader title="Overdue Invoices" />
        <ErrorPanel message={`Failed to load invoices: ${message}`} retryHref={currentHref} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Overdue Invoices"
        subtitle="Every row is a real, persisted decision from the live 900-invoice pool -- scored, retrieved, policy-checked, and acted on."
        actions={<RefreshButton />}
      />

      <InvoiceFilters currentState={currentState} segment={segment} invoiceNumber={invoiceNumber} />

      {invoices.length === 0 ? (
        <EmptyState>No invoices match these filters.</EmptyState>
      ) : (
        // Second attempt at the sticky header still didn't stick -- rather
        // than keep guessing at the overflow-hidden ancestor's exact
        // behavior, it's removed entirely here. NO ancestor between the
        // sticky <thead> and the real page scroll now has any `overflow`
        // property at all, which is the only fully unambiguous way to
        // guarantee `sticky` tracks page scroll. Rounded corners are done
        // per-cell instead (top corners on the header's outer cells, bottom
        // corners on the last row's outer cells via InvoiceRow's `isLast`)
        // rather than relying on a clipping wrapper. Trade-off: dropped the
        // overflow-x-auto horizontal-scroll-on-mobile wrapper along with
        // it -- console pages are desktop-first already (the sidebar nav
        // itself is desktop-only), so this isn't a new gap.
        <div className="rounded-panel border border-border">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-20">
              <tr className="border-b border-border bg-surface-2/95 text-left backdrop-blur-md">
                <th className="w-1 rounded-tl-panel p-0" />
                <th className="label !text-text px-4 py-3">Invoice #</th>
                <th className="label !text-text px-4 py-3">Customer</th>
                <th className="label !text-text px-4 py-3 text-right">Amount</th>
                <th className="label !text-text px-4 py-3">Due Date</th>
                <th className="label !text-text px-4 py-3">Status</th>
                <th className="label !text-text px-4 py-3 text-right">Recoverability</th>
                <th className="label !text-text rounded-tr-panel px-4 py-3">Next Action</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice, i) => (
                <InvoiceRow key={invoice.invoice_id} invoice={invoice} index={i} isLast={i === invoices.length - 1} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-5 flex items-center justify-between text-sm">
        <span className="text-text-faint">
          Showing {invoices.length > 0 ? offset + 1 : 0}
          {"–"}
          {offset + invoices.length}
        </span>
        <div className="flex gap-2">
          {offset > 0 && (
            <Link
              href={buildHref(currentState, segment, invoiceNumber, Math.max(0, offset - PAGE_SIZE))}
              className="flex items-center gap-1 rounded-[var(--radius-control)] border border-border px-3 py-1.5 text-text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              <ChevronLeft size={14} /> Previous
            </Link>
          )}
          {invoices.length === PAGE_SIZE && (
            <Link
              href={buildHref(currentState, segment, invoiceNumber, offset + PAGE_SIZE)}
              className="flex items-center gap-1 rounded-[var(--radius-control)] border border-border px-3 py-1.5 text-text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              Next <ChevronRight size={14} />
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
