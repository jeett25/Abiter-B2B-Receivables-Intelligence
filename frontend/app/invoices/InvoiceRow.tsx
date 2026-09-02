"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { InvoiceSummary } from "@/lib/types";
import { ActionBadge, StateBadge, formatCurrency, stateMeta } from "@/lib/ui";

const TONE_BAR: Record<string, string> = {
  wait: "bg-status-wait",
  remind: "bg-status-remind",
  escalate: "bg-status-escalate",
  dispute: "bg-status-dispute",
  success: "bg-status-success",
  danger: "bg-status-danger",
  neutral: "bg-text-faint",
};

// Recoverability fill is tiered by score, not tied to the row's own status
// tone -- a viewer scanning the column wants "how likely is this to
// recover" at a glance, independent of what action/state it's currently in.
function recoverabilityColor(pct: number): string {
  if (pct >= 65) return "bg-accent";
  if (pct >= 35) return "bg-status-escalate";
  return "bg-status-danger";
}

export default function InvoiceRow({ invoice, index, isLast }: { invoice: InvoiceSummary; index: number; isLast?: boolean }) {
  const router = useRouter();
  const recoverabilityPct = Math.round(invoice.recoverability_score * 100);
  const tone = stateMeta(invoice.current_state).tone;
  const href = `/invoices/${invoice.invoice_id}`;
  const barColor = recoverabilityColor(recoverabilityPct);

  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: Math.min(index * 0.012, 0.3) }}
      onClick={() => router.push(href)}
      className="group cursor-pointer border-b border-border/50 last:border-0 hover:bg-surface-hover/60"
    >
      <td className={`w-1 p-0 ${isLast ? "rounded-bl-panel" : ""}`}>
        <span className={`block h-full w-0.5 ${TONE_BAR[tone]} opacity-0 transition-opacity group-hover:opacity-100`} />
      </td>
      <td className="px-4 py-3.5">
        <Link
          href={href}
          onClick={(e) => e.stopPropagation()}
          className="font-mono-tabular text-sm font-medium text-accent-text transition-colors hover:text-accent-hover"
        >
          {invoice.invoice_number}
        </Link>
      </td>
      <td className="px-4 py-3.5 text-text">{invoice.customer_name}</td>
      <td className="px-4 py-3.5 text-right font-mono-tabular text-text">{formatCurrency(invoice.amount)}</td>
      <td className="px-4 py-3.5 text-text-muted">{invoice.due_date}</td>
      <td className="px-4 py-3.5">
        <StateBadge state={invoice.current_state} />
      </td>
      <td className="px-4 py-3.5">
        <div className="flex items-center justify-end gap-2.5">
          <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-2">
            <div
              className={`h-full rounded-full transition-[width] duration-500 ${barColor}`}
              style={{ width: `${recoverabilityPct}%` }}
            />
          </div>
          <span className="w-9 text-right font-mono-tabular text-xs text-text-muted">{recoverabilityPct}%</span>
        </div>
      </td>
      <td className={`px-4 py-3.5 ${isLast ? "rounded-br-panel" : ""}`}>
        <ActionBadge action={invoice.next_action} />
      </td>
    </motion.tr>
  );
}
