"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronDown, Clock, RefreshCw, ShieldOff, XCircle, Zap } from "lucide-react";
import type { ComponentType } from "react";
import { DemoFixture } from "@/lib/types";

// Renamed from "Load demo case" (2026-09-02) -- that label communicated
// nothing about what it does or why a visitor would click it. "Example
// scenarios" + the intro line below spell out the actual value: these are
// pinned invoices chosen specifically to each demonstrate a different real
// decision the engine makes, not a random invoice from the 900.
//
// `fixtures` is empty when GET /api/demo-fixtures failed (see layout.tsx) --
// the two filter-based entries still work regardless, since they don't
// depend on that endpoint at all.

function iconFor(action: string): ComponentType<{ size?: number; className?: string }> {
  const a = action.toLowerCase();
  if (a.includes("wait")) return Clock;
  if (a.includes("escalate") || a.includes("voice")) return AlertTriangle;
  if (a.includes("reassess")) return RefreshCw;
  if (a.includes("stop") || a.includes("suppress")) return XCircle;
  return Zap;
}

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
        className="flex items-center gap-1.5 text-sm font-medium text-text-muted transition-colors hover:text-text"
      >
        Example scenarios
        <ChevronDown size={14} className={open ? "rotate-180 transition-transform duration-200" : "transition-transform duration-200"} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.97 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            className="absolute right-0 z-50 mt-2 w-[27rem] origin-top-right overflow-hidden rounded-2xl border border-border bg-surface-2/95 shadow-elevated backdrop-blur-xl"
          >
            <p className="border-b border-border/70 px-4 py-3 text-xs leading-relaxed text-text-faint">
              Six real invoices, pre-selected because each one shows a different decision the engine makes —
              skip searching through the full list.
            </p>
            <ul className="max-h-[70vh] overflow-y-auto p-1.5">
              {fixtures.map((f) => {
                const Icon = iconFor(f.expected_action);
                return (
                  <li key={f.key}>
                    <Link
                      href={`/invoices/${f.invoice_id}`}
                      className="group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-surface-hover"
                    >
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text transition-colors group-hover:bg-accent group-hover:text-white">
                        <Icon size={14} />
                      </span>
                      <span>
                        <div className="text-sm font-medium text-text">{f.label}</div>
                        <div className="text-xs text-text-faint">
                          {f.invoice_number} · decides <span className="text-accent-text">{f.expected_action}</span>
                        </div>
                      </span>
                    </Link>
                  </li>
                );
              })}
              <li className="mx-3 my-1.5 h-px bg-border" />
              <li>
                <Link
                  href="/invoices?current_state=dispute_review"
                  className="group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-surface-hover"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-status-dispute-soft text-status-dispute">
                    <AlertTriangle size={14} />
                  </span>
                  <span>
                    <div className="text-sm font-medium text-text">Dispute in progress</div>
                    <div className="text-xs text-text-faint">filtered list of 56 real disputed invoices — pick any</div>
                  </span>
                </Link>
              </li>
              <li>
                <Link
                  href="/invoices?current_state=closed_abandoned"
                  className="group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-surface-hover"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-text-faint">
                    <ShieldOff size={14} />
                  </span>
                  <span>
                    <div className="text-sm font-medium text-text">Abandoned (edge case)</div>
                    <div className="text-xs text-text-faint">
                      intentionally empty today — verified 0 invoices ever hit this state, not a bug
                    </div>
                  </span>
                </Link>
              </li>
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
