"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll, useSpring } from "framer-motion";
import { RotateCcw } from "lucide-react";

const STAGES = [
  {
    key: "event",
    label: "Event",
    detail: "An invoice goes overdue, a customer replies, or a promise to pay breaks. Every one of these is a real, timestamped trigger — not a scheduled batch job.",
  },
  {
    key: "predict",
    label: "Predict",
    detail: "Calibrated XGBoost models score recovery probability and promise-to-pay confidence, trained strictly point-in-time so no feature ever leaks the future.",
  },
  {
    key: "retrieve",
    label: "Retrieve",
    detail: "Hybrid BM25 + pgvector search pulls similar historical cases, fused by Reciprocal Rank Fusion, so every decision has grounded precedent behind it.",
  },
  {
    key: "decide",
    label: "Decide",
    detail: "Expected-value economics rank every candidate action, then a deterministic Policy/Safety Gate — never an LLM — makes the final call.",
  },
  {
    key: "act",
    label: "Act",
    detail: "Email, WhatsApp, Voice, a real Razorpay Payment Link, or Escalate — whichever the economics and policy gate together approve, executed for real.",
  },
  {
    key: "measure",
    label: "Measure",
    detail: "A randomized holdout — treatment vs. control — measures what actually happened, not what the model assumed would happen.",
  },
  {
    key: "learn",
    label: "Learn",
    detail: "Measured incremental recovery corrects the Economics Engine's own uplift assumptions for the next decision — a real feedback loop, not a one-shot model.",
  },
];

// Rebuilt again (2026-09-02): the previous version used a CSS Grid
// col-start-1/col-start-2 + text-align trick to alternate sides, which
// wasn't rendering correctly (every row ended up in the same visual
// position). Replaced with an explicit, unambiguous layout -- each row
// always renders BOTH a left half and a right half (each a real sm:w-1/2
// flex child), and the actual content only ever goes into whichever half
// matches that step's side. No auto-placement, no alignment trick that can
// silently not apply -- the DOM structure itself guarantees the side.
export default function PipelineViz() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start 0.8", "end 0.35"],
  });
  const lineProgress = useSpring(scrollYProgress, { stiffness: 90, damping: 24, mass: 0.4 });

  return (
    <div ref={containerRef} className="relative py-4">
      <div className="absolute top-0 bottom-0 left-3 w-px bg-border sm:left-1/2" />
      <motion.div
        className="absolute top-0 left-3 w-px origin-top bg-gradient-to-b from-accent to-accent-text sm:left-1/2"
        style={{ scaleY: lineProgress, height: "100%" }}
      />

      <ol className="relative space-y-1">
        {STAGES.map((stage, i) => (
          <StageRow key={stage.key} stage={stage} index={i} onRight={i % 2 === 1} />
        ))}
      </ol>

      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.8 }}
        transition={{ delay: 0.2, duration: 0.4 }}
        className="relative mt-4 ml-9 flex items-start gap-2.5 rounded-lg border border-accent/25 bg-accent-soft/30 px-4 py-3 text-xs text-accent-text sm:ml-[calc(50%+2rem)]"
      >
        <motion.span
          animate={{ rotate: -360 }}
          transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
          className="mt-0.5 shrink-0"
        >
          <RotateCcw size={14} />
        </motion.span>
        <span>
          Learn loops back into Predict — this feedback loop is what separates a decision engine from a
          rules script.
        </span>
      </motion.div>
    </div>
  );
}

function StageContent({ stage, active, align }: { stage: (typeof STAGES)[number]; active: boolean; align: "left" | "right" }) {
  return (
    <div className={align === "right" ? "text-right" : ""}>
      <span className={`font-display text-lg font-semibold transition-colors duration-300 ${active ? "text-text" : "text-text-faint"}`}>
        {stage.label}
      </span>
      <AnimatePresence initial={false}>
        {active && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <p className={`max-w-md pt-1.5 text-sm leading-relaxed text-text-muted ${align === "right" ? "ml-auto" : ""}`}>
              {stage.detail}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function StageRow({ stage, index, onRight }: { stage: (typeof STAGES)[number]; index: number; onRight: boolean }) {
  const ref = useRef<HTMLLIElement>(null);
  const [active, setActive] = useState(index === 0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.65", "end 0.35"] });

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    setActive(v > 0.15 && v < 0.85);
  });

  return (
    <motion.li
      ref={ref}
      className="relative py-3 pl-9 sm:flex sm:items-start sm:pl-0"
      initial={{ opacity: 0, x: -12 }}
      whileInView={{ opacity: 1, x: 0 }}
      viewport={{ once: true, amount: 0.6 }}
      transition={{ duration: 0.4 }}
    >
      <motion.span
        className="absolute top-3.5 left-3 z-10 flex h-6 w-6 -translate-x-1/2 items-center justify-center rounded-full border-2 bg-bg sm:left-1/2"
        animate={{
          borderColor: active ? "var(--color-accent)" : "var(--color-border-strong)",
          scale: active ? 1.15 : 1,
        }}
        transition={{ duration: 0.3 }}
      >
        {active && <span className="absolute h-full w-full animate-ping rounded-full bg-accent/30" />}
        <span className={`label !text-[9px] !tracking-normal ${active ? "text-accent-text" : "text-text-faint"}`}>
          {index + 1}
        </span>
      </motion.span>

      {/* Mobile: single column, always show content (no left/right split). */}
      <div className="sm:hidden">
        <StageContent stage={stage} active={active} align="left" />
      </div>

      {/* Desktop: two ALWAYS-present halves, content only in the matching
          one -- guarantees the side, no auto-placement involved. */}
      <div className="hidden sm:block sm:w-1/2 sm:pr-10">{!onRight && <StageContent stage={stage} active={active} align="right" />}</div>
      <div className="hidden sm:block sm:w-1/2 sm:pl-10">{onRight && <StageContent stage={stage} active={active} align="left" />}</div>
    </motion.li>
  );
}
