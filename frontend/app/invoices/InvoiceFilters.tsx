"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import { AccountCurrentState } from "@/lib/types";
import { cx } from "@/lib/ui";

// Live filtering (2026-09-02): invoice_number now filters as you type
// (debounced 350ms so it doesn't fire a navigation on every keystroke),
// no Filter button/submit needed anymore. Segment changed from a free-text
// input to a dropdown -- confirmed against synthetic/generator.py's own
// SEGMENTS constant that there are exactly three real values in this
// dataset (SMB / Mid-Market / Enterprise), so a dropdown is both more
// correct (can't typo/miss a segment) and simpler than the text field it
// replaced.

// Pruned from the full 14-value AccountCurrentState enum (2026-09-02): five
// of those values -- assessment, monitoring, broken, reassess, and plain
// closed -- are defined in the schema but never actually assigned by any
// rule in this codebase (see CLAUDE.md's account_state notes and
// app/agent/DECISIONS.md) -- confirmed 0 rows across the whole dataset, not
// just today, so listing them here was a guaranteed dead end every time.
// overdue/promise/kept are kept even though currently empty -- those ARE
// reachable given the right event sequence (e.g. a live promise-extraction
// round), just not populated by a plain INVOICE_OVERDUE batch pass.
const CURRENT_STATE_OPTIONS: AccountCurrentState[] = [
  "overdue",
  "wait",
  "remind",
  "escalate",
  "promise",
  "kept",
  "closed_paid",
  "closed_abandoned",
  "dispute_review",
];

const SEGMENT_OPTIONS = ["SMB", "Mid-Market", "Enterprise"];

const inputClass =
  "rounded-[var(--radius-control)] border border-border bg-surface-2 text-sm text-text placeholder:text-text-faint transition-colors focus:border-accent/50 focus:ring-2 focus:ring-accent/30 focus:outline-none";

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
  const [search, setSearch] = useState(invoiceNumber ?? "");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    const value = e.target.value;
    setSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => navigate(currentState ?? "", segment ?? "", value), 350);
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const hasFilters = Boolean(currentState || segment || invoiceNumber);

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2.5">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-faint" />
        <input
          type="text"
          value={search}
          onChange={handleSearchChange}
          placeholder="Search invoice # (e.g. INV-10184)"
          className={cx(inputClass, "w-64 py-2 pr-3 pl-9")}
        />
      </div>
      <select
        value={currentState ?? ""}
        onChange={(e) => navigate(e.target.value, segment ?? "", search)}
        className={cx(inputClass, "px-3 py-2")}
      >
        <option value="">All statuses</option>
        {CURRENT_STATE_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select
        value={segment ?? ""}
        onChange={(e) => navigate(currentState ?? "", e.target.value, search)}
        className={cx(inputClass, "px-3 py-2")}
      >
        <option value="">All segments</option>
        {SEGMENT_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {hasFilters && (
        <button
          type="button"
          onClick={() => {
            setSearch("");
            navigate("", "", "");
          }}
          className="flex items-center gap-1 text-sm text-text-muted transition-colors hover:text-text"
        >
          <X size={13} /> Clear
        </button>
      )}
    </div>
  );
}
