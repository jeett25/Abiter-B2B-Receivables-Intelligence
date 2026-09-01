import Link from "next/link";
import { ApiError, listInvoices } from "@/lib/api";
import RefreshButton from "../RefreshButton";
import InvoiceFilters from "./InvoiceFilters";

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
        <h1>Overdue Invoices</h1>
        <p role="alert" style={{ color: "#b00020" }}>
          Failed to load invoices: {message}
        </p>
        {/* Retries the SAME filtered/paginated URL, not a bare reset to
            /invoices -- a failed fetch shouldn't also discard the user's
            filters. */}
        <Link href={currentHref}>Retry</Link>
      </div>
    );
  }

  return (
    <div>
      <h1>
        Overdue Invoices <RefreshButton />
      </h1>

      <InvoiceFilters currentState={currentState} segment={segment} invoiceNumber={invoiceNumber} />

      {invoices.length === 0 ? (
        <p>No invoices match these filters.</p>
      ) : (
        <table border={1} cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th>Invoice #</th>
              <th>Customer</th>
              <th>Amount</th>
              <th>Due Date</th>
              <th>Status</th>
              <th>Recoverability</th>
              <th>Next Action</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((invoice) => (
              <tr key={invoice.invoice_id}>
                <td>
                  <Link href={`/invoices/${invoice.invoice_id}`}>{invoice.invoice_number}</Link>
                </td>
                <td>{invoice.customer_name}</td>
                <td>Rs.{invoice.amount.toLocaleString("en-IN")}</td>
                <td>{invoice.due_date}</td>
                <td>{invoice.current_state}</td>
                <td>{(invoice.recoverability_score * 100).toFixed(0)}%</td>
                <td>{invoice.next_action ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: "1em", display: "flex", gap: "1em" }}>
        {offset > 0 && (
          <Link href={buildHref(currentState, segment, invoiceNumber, Math.max(0, offset - PAGE_SIZE))}>&larr; Previous</Link>
        )}
        {invoices.length === PAGE_SIZE && (
          <Link href={buildHref(currentState, segment, invoiceNumber, offset + PAGE_SIZE)}>Next &rarr;</Link>
        )}
      </div>
    </div>
  );
}
