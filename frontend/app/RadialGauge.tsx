"use client";

import { motion } from "framer-motion";

// Shared across invoice detail (recovery/PTP probability) and metrics
// (baseline/engine recovery rate) -- moved here from
// invoices/[invoiceId]/ once the metrics redesign needed it too.
export default function RadialGauge({
  value,
  label,
  size = 128,
  strokeWidth = 10,
  color = "var(--color-accent)",
}: {
  value: number;
  // Optional -- when omitted, no label is rendered inside the ring at all
  // (the caller places its own, wider label block below the gauge instead).
  // A caption forced to fit inside the ring's own diameter is what caused
  // long strategy names ("Baseline (email everyone)") to wrap into 3 lines
  // and spill past the stroke on the metrics page.
  label?: string;
  size?: number;
  strokeWidth?: number;
  color?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.round(value * 100);

  return (
    <div className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-border)" strokeWidth={strokeWidth} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - value) }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="font-mono-tabular text-2xl font-semibold"
          style={{ color }}
        >
          {pct}%
        </motion.span>
        {label && <span className="label mt-0.5 !text-[9px]">{label}</span>}
      </div>
    </div>
  );
}
