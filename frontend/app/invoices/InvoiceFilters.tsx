"use client";

import { useRouter } from "next/navigation";
import { AccountCurrentState } from "@/lib/types";

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
    <form
      onSubmit={handleSubmit}
      style={{ marginBottom: "1em", display: "flex", gap: "1em", alignItems: "center" }}
    >
      <label>
        Invoice #:{" "}
        <input
          type="text"
          name="invoice_number"
          defaultValue={invoiceNumber ?? ""}
          placeholder="e.g. 10184 or INV-10184"
        />
      </label>
      <label>
        Status:{" "}
        <select name="current_state" defaultValue={currentState ?? ""} onChange={handleStatusChange}>
          <option value="">All</option>
          {CURRENT_STATE_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <label>
        Segment:{" "}
        <input type="text" name="segment" defaultValue={segment ?? ""} placeholder="e.g. SMB" />
      </label>
      <button type="submit">Filter</button>
      {hasFilters && (
        <a href="/invoices" onClick={(e) => { e.preventDefault(); navigate("", "", ""); }}>
          Clear filters
        </a>
      )}
    </form>
  );
}
