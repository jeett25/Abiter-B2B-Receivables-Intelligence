"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { InvoiceSummary } from "@/lib/types";
import { ActionBadge, StateBadge, formatCurrency } from "@/lib/ui";

export default function InvoiceRow({ invoice, index }: { invoice: InvoiceSummary; index: number }) {
  const recoverabilityPct = Math.round(invoice.recoverability_score * 100);
  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: Math.min(index * 0.015, 0.3) }}
      className="border-b border-border/60 last:border-0 hover:bg-surface-hover transition-colors"
    >
      <td className="px-4 py-3">
        <Link href={`/invoices/${invoice.invoice_id}`} className="font-mono-tabular text-sm font-medium text-accent-text hover:text-accent-hover">
          {invoice.invoice_number}
        </Link>
      </td>
      <td className="px-4 py-3 text-text">{invoice.customer_name}</td>
      <td className="px-4 py-3 text-right font-mono-tabular text-text">{formatCurrency(invoice.amount)}</td>
      <td className="px-4 py-3 text-text-muted">{invoice.due_date}</td>
      <td className="px-4 py-3">
        <StateBadge state={invoice.current_state} />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-end gap-2">
          <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${recoverabilityPct}%` }}
            />
          </div>
          <span className="w-9 text-right font-mono-tabular text-xs text-text-muted">{recoverabilityPct}%</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <ActionBadge action={invoice.next_action} />
      </td>
    </motion.tr>
  );
}
