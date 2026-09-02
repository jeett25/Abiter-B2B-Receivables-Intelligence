"use client";

import { AnimatePresence, motion } from "framer-motion";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// Keyed on pathname so every real navigation (invoices <-> detail <->
// metrics <-> observability <-> landing) gets a soft settle instead of an
// abrupt content swap -- the one page-level "transition" this app didn't
// have anywhere outside individual components' own entrance animations
// (InvoiceRow's stagger, RadialGauge's stroke draw, etc.). Deliberately NOT
// mode="wait": overlapping the outgoing and incoming trees avoids a blank
// gap between them, at the cost of a brief height jump on very
// different-length pages -- a smaller cost than a page that visibly pauses
// on every click.
export default function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <AnimatePresence initial={false}>
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
