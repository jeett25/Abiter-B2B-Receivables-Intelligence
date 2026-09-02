"use client";

import Link from "next/link";
import { ArrowRight, LineChart } from "lucide-react";
import { motion } from "framer-motion";

export default function HeroActions() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 24, delay: 0.5 }}
      className="flex flex-wrap items-center gap-4"
    >
      <Link
        href="/invoices"
        className="group relative inline-flex items-center gap-2 overflow-hidden rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-white shadow-accent transition-transform duration-200 hover:scale-[1.02] active:scale-[0.98]"
      >
        {/* Sheen sweep on hover -- a diagonal highlight passes across the
            button, timed with the CSS transition rather than looping
            forever (motion should signal "hover me", not distract at rest). */}
        <span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 ease-out group-hover:translate-x-full" />
        <span className="relative">Open Console</span>
        <ArrowRight size={16} className="relative transition-transform duration-200 group-hover:translate-x-1" />
      </Link>
      <Link
        href="/metrics"
        className="group relative inline-flex items-center gap-2 rounded-lg border border-border px-6 py-3 text-sm font-medium text-text-muted transition-all duration-200 hover:border-accent/50 hover:text-text hover:shadow-[0_0_0_1px_rgb(61_116_240/0.3),0_0_24px_-8px_rgb(61_116_240/0.5)] active:scale-[0.98]"
      >
        <LineChart size={16} className="text-text-faint transition-colors duration-200 group-hover:text-accent-text" />
        View proof metrics
      </Link>
    </motion.div>
  );
}
