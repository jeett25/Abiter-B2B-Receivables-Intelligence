import Link from "next/link";
import { ApiError, listInvoices } from "@/lib/api";
import { ErrorPanel, EmptyState, PageHeader } from "@/lib/ui";
import RefreshButton from "../RefreshButton";
import InvoiceFilters from "./InvoiceFilters";
import InvoiceRow from "./InvoiceRow";

// Screen 1 (master doc Day 3): overdue invoices, status, recoverability
// score, next action. Day 6: connected to the real GET /api/invoices.
// Pagination is driven by the URL's searchParams via plain <Link>s (Server
// Component, no client JS needed there); filtering is delegated to
// InvoiceFilters, a small client component, so selecting a Status applies
// immediately via client-side navigation instead of requiring a submit click.

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
        <div className="overflow-hidden rounded-2xl border border-border">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-2/60 text-left text-xs font-medium uppercase tracking-wide text-text-muted">
                  <th className="px-4 py-3">Invoice #</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Due Date</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Recoverability</th>
                  <th className="px-4 py-3">Next Action</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((invoice, i) => (
                  <InvoiceRow key={invoice.invoice_id} invoice={invoice} index={i} />
                ))}
              </tbody>
            </table>
          </div>
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
              className="rounded-lg border border-border px-3 py-1.5 text-text-muted hover:text-text hover:border-border-strong transition-colors"
            >
              ← Previous
            </Link>
          )}
          {invoices.length === PAGE_SIZE && (
            <Link
              href={buildHref(currentState, segment, invoiceNumber, offset + PAGE_SIZE)}
              className="rounded-lg border border-border px-3 py-1.5 text-text-muted hover:text-text hover:border-border-strong transition-colors"
            >
              Next →
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
