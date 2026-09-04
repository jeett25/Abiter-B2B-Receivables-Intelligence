"use client";

import { useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronRight, Gauge, Home, LineChart, Receipt, ShieldOff } from "lucide-react";
import type { ComponentType } from "react";
import { DemoFixture } from "@/lib/types";
import { cx } from "@/lib/ui";

// Console-only navigation shell (2026-09-02) -- the landing page keeps its
// own transparent top nav (SiteChrome.tsx decides which one renders per
// route). Collapsed to an icon rail by default; hovering the rail expands
// it as a floating overlay (position:fixed + higher z-index) rather than
// pushing page content, so the expand/collapse never reflows the table
// underneath it.

const NAV_ITEMS = [
  { href: "/invoices", label: "Invoices", icon: Receipt },
  { href: "/metrics", label: "Metrics", icon: LineChart },
  { href: "/observability", label: "System Health", icon: Gauge },
];

function iconForAction(action: string): ComponentType<{ size?: number; className?: string }> {
  const a = action.toLowerCase();
  if (a.includes("escalate") || a.includes("voice")) return AlertTriangle;
  if (a.includes("stop") || a.includes("suppress")) return ShieldOff;
  return Receipt;
}

export default function ConsoleSidebar({ fixtures }: { fixtures: DemoFixture[] }) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const [scenariosOpen, setScenariosOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function open() {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setExpanded(true);
  }
  function scheduleClose() {
    closeTimer.current = setTimeout(() => {
      setExpanded(false);
      setScenariosOpen(false);
    }, 200);
  }

  return (
    <>
      {/* Spacer -- reserves the collapsed rail's width in normal flow so
          page content starts at the right offset; the actual rail is
          fixed/overlaid on top of this. */}
      <div className="hidden w-[76px] shrink-0 sm:block" />

      <motion.aside
        onMouseEnter={open}
        onMouseLeave={scheduleClose}
        animate={{ width: expanded ? 248 : 76 }}
        transition={{ type: "spring", stiffness: 400, damping: 38 }}
        className="fixed top-0 left-0 z-30 hidden h-full flex-col border-r border-border/60 bg-surface/80 backdrop-blur-xl sm:flex"
      >
        <Link href="/" className="flex h-[76px] shrink-0 items-center gap-3 px-6">
          <Image src="/logo.png" alt="Arbiter" width={30} height={30} className="shrink-0 rounded-[7px]" />
          <AnimatePresence>
            {expanded && (
              <motion.span
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="font-display text-sm font-semibold whitespace-nowrap text-text"
              >
                Arbiter
              </motion.span>
            )}
          </AnimatePresence>
        </Link>

        <nav className="flex flex-1 flex-col gap-1 px-3.5 pt-2">
          {NAV_ITEMS.map((item) => {
            const active = pathname?.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cx(
                  "flex items-center gap-3.5 rounded-xl px-2.5 py-2.5 transition-colors",
                  active ? "bg-accent-soft text-accent-text" : "text-text-muted hover:bg-surface-hover hover:text-text"
                )}
              >
                <Icon size={19} className="shrink-0" />
                <AnimatePresence>
                  {expanded && (
                    <motion.span
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.15 }}
                      className="text-sm font-medium whitespace-nowrap"
                    >
                      {item.label}
                    </motion.span>
                  )}
                </AnimatePresence>
              </Link>
            );
          })}

          {/* Example scenarios -- flyout opens to the right instead of
              downward (this lives in a left rail, not a top bar). */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setScenariosOpen((v) => !v)}
              className={cx(
                "flex w-full items-center gap-3.5 rounded-xl px-2.5 py-2.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text",
                scenariosOpen && "bg-surface-hover text-text"
              )}
            >
              <span className="relative shrink-0">
                <span className="label !text-[10px] !tracking-normal flex h-[19px] w-[19px] items-center justify-center rounded-full border border-current">
                  6
                </span>
              </span>
              <AnimatePresence>
                {expanded && (
                  <motion.span
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="flex flex-1 items-center justify-between text-sm font-medium whitespace-nowrap"
                  >
                    Example scenarios
                    <ChevronRight size={14} className={scenariosOpen ? "rotate-90 transition-transform" : "transition-transform"} />
                  </motion.span>
                )}
              </AnimatePresence>
            </button>

            <AnimatePresence>
              {scenariosOpen && expanded && (
                <motion.div
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.15 }}
                  className="absolute top-0 left-full ml-2 w-72 overflow-hidden rounded-2xl border border-border bg-surface-2/95 py-1.5 shadow-elevated backdrop-blur-xl"
                >
                  {fixtures.map((f) => {
                    const Icon = iconForAction(f.expected_action);
                    return (
                      <Link
                        key={f.key}
                        href={`/invoices/${f.invoice_id}`}
                        className="flex items-start gap-3 px-3.5 py-2.5 transition-colors hover:bg-surface-hover"
                      >
                        <Icon size={14} className="mt-0.5 shrink-0 text-accent-text" />
                        <span>
                          <div className="text-sm font-medium text-text">{f.label}</div>
                          <div className="text-xs text-text-faint">{f.invoice_number}</div>
                        </span>
                      </Link>
                    );
                  })}
                  <div className="mx-3.5 my-1.5 h-px bg-border" />
                  <Link
                    href="/invoices?current_state=dispute_review"
                    className="flex items-center gap-3 px-3.5 py-2.5 text-sm text-text transition-colors hover:bg-surface-hover"
                  >
                    <AlertTriangle size={14} className="text-status-dispute" /> Disputes in progress
                  </Link>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </nav>

        <Link
          href="/"
          className="flex shrink-0 items-center gap-3.5 border-t border-border/60 px-6 py-4 text-text-faint transition-colors hover:text-text"
        >
          <Home size={17} className="shrink-0" />
          <AnimatePresence>
            {expanded && (
              <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-xs whitespace-nowrap">
                Back to landing
              </motion.span>
            )}
          </AnimatePresence>
        </Link>
      </motion.aside>
    </>
  );
}
