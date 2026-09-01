"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { DemoFixture } from "@/lib/types";

// `fixtures` is empty when GET /api/demo-fixtures failed (see layout.tsx) --
// the two filter-based entries still work regardless, since they don't
// depend on that endpoint at all.
export default function DemoCaseMenu({ fixtures }: { fixtures: DemoFixture[] }) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scheduleClose() {
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  }
  function cancelClose() {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }

  return (
    <div className="relative" onMouseEnter={() => { cancelClose(); setOpen(true); }} onMouseLeave={scheduleClose}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-muted hover:text-text hover:border-border-strong transition-colors"
      >
        Load demo case
        <svg width="10" height="10" viewBox="0 0 10 10" className={open ? "rotate-180 transition-transform" : "transition-transform"}>
          <path d="M1 3l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.14 }}
            className="absolute right-0 z-50 mt-2 w-96 origin-top-right rounded-xl border border-border bg-surface-2 p-1.5 shadow-elevated"
          >
            {fixtures.map((f) => (
              <li key={f.key}>
                <Link
                  href={`/invoices/${f.invoice_id}`}
                  className="block rounded-lg px-3 py-2 hover:bg-surface-hover transition-colors"
                >
                  <div className="text-sm font-medium text-text">{f.label}</div>
                  <div className="text-xs text-text-faint">
                    {f.invoice_number} · expects {f.expected_action}
                  </div>
                </Link>
              </li>
            ))}
            <li className="my-1 h-px bg-border" />
            <li>
              <Link
                href="/invoices?current_state=dispute_review"
                className="block rounded-lg px-3 py-2 hover:bg-surface-hover transition-colors"
              >
                <div className="text-sm font-medium text-text">Dispute</div>
                <div className="text-xs text-text-faint">filtered list -- no single pinned fixture, pick any</div>
              </Link>
            </li>
            <li>
              <Link
                href="/invoices?current_state=closed_abandoned"
                className="block rounded-lg px-3 py-2 hover:bg-surface-hover transition-colors"
              >
                <div className="text-sm font-medium text-text">Abandoned</div>
                <div className="text-xs text-text-faint">verified: 0 live invoices resolve here today -- not a bug</div>
              </Link>
            </li>
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
