"use client";

import { motion } from "framer-motion";

const STAGES = [
  { key: "event", label: "Event", detail: "Invoice overdue, customer replies, promise breaks" },
  { key: "predict", label: "Predict", detail: "Calibrated XGBoost recovery + promise-to-pay models" },
  { key: "retrieve", label: "Retrieve", detail: "Hybrid BM25 + pgvector case retrieval, RRF fused" },
  { key: "decide", label: "Decide", detail: "Expected-value economics + deterministic policy gate" },
  { key: "act", label: "Act", detail: "Email · WhatsApp · Voice · Payment Link · Escalate" },
  { key: "measure", label: "Measure", detail: "Randomized holdout attribution, not vanity metrics" },
  { key: "learn", label: "Learn", detail: "Measured uplift corrects the next decision's economics" },
];

export default function PipelineViz() {
  return (
    <div className="relative overflow-x-auto py-4">
      <div className="flex min-w-[900px] items-stretch gap-3 sm:min-w-0">
        {STAGES.map((stage, i) => (
          <div key={stage.key} className="flex flex-1 items-center">
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.45, delay: i * 0.08 }}
              className="group relative flex-1 rounded-2xl border border-border bg-surface/70 p-4 backdrop-blur-sm transition-colors hover:border-accent/40"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft font-mono-tabular text-xs font-semibold text-accent-text">
                {String(i + 1).padStart(2, "0")}
              </div>
              <div className="mt-3 text-sm font-semibold text-text">{stage.label}</div>
              <div className="mt-1 text-xs leading-relaxed text-text-faint">{stage.detail}</div>
              <motion.div
                className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100"
                style={{
                  background:
                    "radial-gradient(120px circle at var(--x,50%) var(--y,50%), rgb(61 127 255 / 0.12), transparent 70%)",
                }}
              />
            </motion.div>
            {i < STAGES.length - 1 && (
              <motion.svg
                width="28"
                height="16"
                viewBox="0 0 28 16"
                className="mx-1 shrink-0 text-text-faint"
                initial={{ opacity: 0 }}
                whileInView={{ opacity: 1 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 + 0.2 }}
              >
                <line x1="0" y1="8" x2="20" y2="8" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 3" />
                <path d="M18 3l6 5-6 5" fill="none" stroke="currentColor" strokeWidth="1.5" />
              </motion.svg>
            )}
          </div>
        ))}
      </div>
      {/* LEARN loops back to PREDICT -- the feedback loop is the entire point of Day 5's attribution engine */}
      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ delay: 0.8 }}
        className="mt-3 flex items-center gap-2 text-xs text-accent-text"
      >
        <svg width="16" height="16" viewBox="0 0 16 16">
          <path d="M3 8a5 5 0 1 1 2 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M3 12v-3h3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        Measured incremental recovery feeds back into the Economics Engine&rsquo;s assumptions — this loop is what
        separates a decision engine from a rules script.
      </motion.div>
    </div>
  );
}
