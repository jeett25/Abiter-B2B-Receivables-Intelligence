"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, MinusCircle } from "lucide-react";
import { RetrievedCase } from "@/lib/types";
import { Badge } from "@/lib/ui";

const PAGE_SIZE = 3;

// Paginated (2026-09-02) -- in the 4-across grouped layout, an unpaginated
// list of 5+ cases made this one card far taller than its three siblings,
// wasting the space below them. Capped at 3 per page so all 4 cards in the
// row stay roughly the same height.
export default function SimilarCasesCard({ cases }: { cases: RetrievedCase[] }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.ceil(cases.length / PAGE_SIZE);
  const visible = cases.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  if (cases.length === 0) {
    // Same icon + centered-block treatment as page.tsx's EmptyPanel (this
    // is a client component, so duplicated rather than cross-imported from
    // a server-component page file) -- an empty card should read as
    // deliberate, not broken.
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
        <MinusCircle size={20} className="text-text-faint" />
        <p className="text-sm text-text-muted">No comparable cases retrieved for this round.</p>
      </div>
    );
  }

  return (
    <div>
      <ul className="space-y-2.5">
        {visible.map((c) => (
          <li key={c.invoice_id} className="rounded-card border border-border bg-surface-2/50 p-3 text-xs">
            <div className="mb-1.5 flex items-center gap-2">
              <Badge tone={c.status === "written_off" ? "danger" : "success"}>{c.status}</Badge>
              <span className="label !text-[9px]">RRF {c.rrf_score.toFixed(3)}</span>
            </div>
            <p className="text-text-muted">{c.case_text}</p>
          </li>
        ))}
      </ul>
      {pageCount > 1 && (
        <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 text-xs text-text-faint">
          <span>
            {page * PAGE_SIZE + 1}–{Math.min(cases.length, page * PAGE_SIZE + PAGE_SIZE)} of {cases.length}
          </span>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-[var(--radius-control)] border border-border p-1 transition-colors hover:border-border-strong hover:text-text disabled:opacity-30"
            >
              <ChevronLeft size={12} />
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={page >= pageCount - 1}
              className="rounded-[var(--radius-control)] border border-border p-1 transition-colors hover:border-border-strong hover:text-text disabled:opacity-30"
            >
              <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
