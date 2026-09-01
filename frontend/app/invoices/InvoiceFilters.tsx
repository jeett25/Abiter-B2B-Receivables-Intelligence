"use client";

import { useRouter } from "next/navigation";
import { AccountCurrentState } from "@/lib/types";
import { cx } from "@/lib/ui";

// Client component (needs onChange) so picking a Status auto-applies
// immediately -- no click required. The Filter button stays for the
// Segment/Invoice # text inputs (and as a fallback/explicit submit for
// Status too). Both paths funnel through the same navigate() so they can
// never disagree about the resulting URL.

const CURRENT_STATE_OPTIONS: AccountCurrentState[] = [
  "overdue",
  "assessment",
  "wait",
  "remind",
  "escalate",
  "promise",
  "monitoring",
  "kept",
  "broken",
  "reassess",
  "closed",
  "closed_paid",
  "closed_abandoned",
  "dispute_review",
];

const inputClass =
  "rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-text placeholder:text-text-faint focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent/50 transition-colors";

export default function InvoiceFilters({
  currentState,
  segment,
  invoiceNumber,
}: {
  currentState?: string;
  segment?: string;
  invoiceNumber?: string;
}) {
  const router = useRouter();

  function navigate(nextCurrentState: string, nextSegment: string, nextInvoiceNumber: string) {
    const params = new URLSearchParams();
    if (nextCurrentState) params.set("current_state", nextCurrentState);
    if (nextSegment) params.set("segment", nextSegment);
    if (nextInvoiceNumber) params.set("invoice_number", nextInvoiceNumber);
    // Changing a filter always resets pagination back to page 1 (offset
    // deliberately omitted here).
    const qs = params.toString();
    router.push(qs ? `/invoices?${qs}` : "/invoices");
  }

  function handleStatusChange(e: React.ChangeEvent<HTMLSelectElement>) {
    navigate(e.target.value, segment ?? "", invoiceNumber ?? "");
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    navigate(
      String(data.get("current_state") ?? ""),
      String(data.get("segment") ?? ""),
      String(data.get("invoice_number") ?? "")
    );
  }

  const hasFilters = Boolean(currentState || segment || invoiceNumber);

  return (
    <form onSubmit={handleSubmit} className="mb-5 flex flex-wrap items-center gap-3">
      <input
        type="text"
        name="invoice_number"
        defaultValue={invoiceNumber ?? ""}
        placeholder="Search invoice # (e.g. INV-10184)"
        className={cx(inputClass, "w-64")}
      />
      <select
        name="current_state"
        defaultValue={currentState ?? ""}
        onChange={handleStatusChange}
        className={inputClass}
      >
        <option value="">All statuses</option>
        {CURRENT_STATE_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <input
        type="text"
        name="segment"
        defaultValue={segment ?? ""}
        placeholder="Segment (e.g. SMB)"
        className={cx(inputClass, "w-40")}
      />
      <button
        type="submit"
        className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white hover:bg-accent-hover transition-colors"
      >
        Filter
      </button>
      {hasFilters && (
        <button
          type="button"
          onClick={() => navigate("", "", "")}
          className="text-sm text-text-muted hover:text-text transition-colors"
        >
          Clear filters
        </button>
      )}
    </form>
  );
}
