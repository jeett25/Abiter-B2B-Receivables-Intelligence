"use client";

import Link from "next/link";
import { motion } from "framer-motion";

export default function HeroActions() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.15 }}
      className="flex flex-wrap items-center gap-3"
    >
      <Link
        href="/invoices"
        className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-elevated hover:bg-accent-hover transition-colors"
      >
        Open Console →
      </Link>
      <Link
        href="/metrics"
        className="rounded-xl border border-border px-5 py-2.5 text-sm font-medium text-text-muted hover:text-text hover:border-border-strong transition-colors"
      >
        View proof metrics
      </Link>
    </motion.div>
  );
}
