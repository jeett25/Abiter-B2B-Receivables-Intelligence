"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useInView, useMotionValueEvent, useReducedMotion, useScroll, useSpring } from "framer-motion";
import { FlaskConical, RefreshCw, Scale, Search, Send, TrendingUp, Zap, type LucideIcon } from "lucide-react";

type Stage = {
  key: string;
  label: string;
  detail: string;
  /** Real, documented figure -- every one traces to CLAUDE.md / DECISIONS.md.
      Never invent one here: the whole point of the chip is that a skimming
      reader can see the pipeline is backed by measured numbers. */
  metric: string;
  Icon: LucideIcon;
};

const STAGES: Stage[] = [
  {
    key: "event",
    label: "Event",
    detail:
      "An invoice goes overdue, a customer replies, or a promise to pay breaks. Every one of these is a real, timestamped trigger — not a scheduled batch job.",
    metric: "8 event types",
    Icon: Zap,
  },
  {
    key: "predict",
    label: "Predict — Recovery, PTP & Root Cause",
    detail:
      "Three calibrated XGBoost models score recovery probability, promise-to-pay confidence, and root cause (cash-flow stress vs. oversight) — all trained strictly point-in-time so no feature ever leaks the future.",
    metric: "Recovery 0.83 · PTP 0.84 · Root Cause 0.76",
    Icon: TrendingUp,
  },
  {
    key: "retrieve",
    label: "Retrieve",
    detail:
      "Hybrid BM25 + pgvector search pulls similar historical cases, fused by Reciprocal Rank Fusion, so every decision has grounded precedent behind it.",
    metric: "2.0× relevance vs. random",
    Icon: Search,
  },
  {
    key: "decide",
    label: "Decide",
    detail:
      "Expected-value economics rank every candidate action, then a deterministic Policy/Safety Gate — never an LLM — makes the final call.",
    metric: "8-rule policy gate",
    Icon: Scale,
  },
  {
    key: "act",
    label: "Act",
    detail:
      "Email, WhatsApp, Voice, a real Razorpay Payment Link, or Escalate — whichever the economics and policy gate together approve, executed for real.",
    metric: "5 channels · real payment links",
    Icon: Send,
  },
  {
    key: "measure",
    label: "Measure",
    detail:
      "A randomized holdout — treatment vs. control — measures what actually happened, not what the model assumed would happen.",
    metric: "811 invoices · 50/50 split",
    Icon: FlaskConical,
  },
  {
    key: "learn",
    label: "Learn",
    detail:
      "Measured incremental recovery corrects the Economics Engine's own uplift assumptions for the next decision — a real feedback loop, not a one-shot model.",
    metric: "ACTION_UPLIFT corrected",
    Icon: RefreshCw,
  },
];

type StageState = "done" | "active" | "pending";

// Rebuilt 2026-09-03 (tiers 1-4). What changed and why, so a future session
// doesn't undo it by accident:
//   - Descriptions are now ALWAYS rendered, dimmed via opacity/scale/blur
//     instead of an AnimatePresence height:0->auto collapse. The old version
//     animated `height`, which is a layout property -- it caused the page to
//     jump on every scroll-activation and can't run on the compositor. Only
//     transform/opacity/filter are animated now.
//   - Nodes carry three states (done / active / pending) driven by one
//     lifted activeIndex, not a per-row boolean. A bare on/off gave no sense
//     of progression -- five of seven stages just read as "disabled".
//   - `animate-ping` (generic Tailwind notification dot) replaced with a
//     layered breathing halo on a spring.
//   - Every looping animation is gated on both `inView` and
//     `prefers-reduced-motion` (the previous version respected neither).
export default function PipelineViz() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [trackHeight, setTrackHeight] = useState(0);

  const reduceMotion = useReducedMotion();
  const inView = useInView(containerRef, { amount: 0.1 });

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start 0.8", "end 0.35"],
  });
  const lineProgress = useSpring(scrollYProgress, { stiffness: 90, damping: 24, mass: 0.4 });

  // Measured (not hardcoded) so the travelling pulse spans the real rail
  // regardless of how the text reflows at different widths.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setTrackHeight(el.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const pulseEnabled = inView && !reduceMotion && trackHeight > 0;

  return (
    <div ref={containerRef} className="relative py-4">
      {/* Static rail */}
      <div aria-hidden className="absolute top-0 bottom-0 left-5 w-px bg-border sm:left-1/2" />

      {/* Scroll-driven progress rail. Slightly wider than the static one and
          given an accent glow so the filled portion reads as "charged". */}
      <motion.div
        aria-hidden
        className="absolute top-0 left-5 w-[2px] origin-top rounded-full bg-gradient-to-b from-accent via-accent to-accent-text sm:left-1/2"
        style={{
          scaleY: lineProgress,
          height: "100%",
          x: "-0.5px",
          boxShadow: "0 0 12px 0 rgb(61 116 240 / 0.45)",
        }}
      />

      {/* Tier 2: a single event travelling the pipeline. Thematically the
          point of the whole component -- this is an event-driven system, so
          show an event moving through it. Paused when offscreen so it isn't
          burning frames on a section nobody is looking at. */}
      {pulseEnabled && (
        <motion.div
          aria-hidden
          className="absolute left-5 z-[1] h-16 w-[2px] -translate-x-1/2 rounded-full sm:left-1/2"
          style={{
            background: "linear-gradient(to bottom, transparent, var(--color-accent-hover), transparent)",
            filter: "blur(0.5px)",
          }}
          initial={{ y: 0, opacity: 0 }}
          animate={{ y: [0, trackHeight], opacity: [0, 1, 1, 0] }}
          transition={{
            y: { duration: 4.5, repeat: Infinity, ease: "easeInOut" },
            opacity: { duration: 4.5, repeat: Infinity, times: [0, 0.12, 0.88, 1], ease: "linear" },
          }}
        />
      )}

      {/* Tier 3: the feedback loop, drawn instead of just described. Wide
          screens only -- on narrower ones the stage text extends too close
          to the edges for the arc to clear it, and the callout below already
          carries the same information in words. */}
      <FeedbackArc active={inView} reduceMotion={!!reduceMotion} />

      <ol className="relative space-y-1">
        {STAGES.map((stage, i) => (
          <StageRow
            key={stage.key}
            stage={stage}
            index={i}
            onRight={i % 2 === 1}
            state={i === activeIndex ? "active" : i < activeIndex ? "done" : "pending"}
            onActivate={setActiveIndex}
            reduceMotion={!!reduceMotion}
          />
        ))}
      </ol>

      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.8 }}
        transition={{ delay: 0.2, duration: 0.4 }}
        className="relative mt-4 ml-14 flex items-start gap-2.5 rounded-lg border border-accent/25 bg-accent-soft/30 px-4 py-3 text-xs text-accent-text sm:ml-[calc(50%+2rem)]"
      >
        <motion.span
          animate={reduceMotion ? undefined : { rotate: -360 }}
          transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
          className="mt-0.5 shrink-0"
        >
          <RotateIcon />
        </motion.span>
        <span>
          Learn loops back into Predict — this feedback loop is what separates a decision engine from a
          rules script.
        </span>
      </motion.div>
    </div>
  );
}

function RotateIcon() {
  return <RefreshCw size={14} />;
}

function FeedbackArc({ active, reduceMotion }: { active: boolean; reduceMotion: boolean }) {
  // viewBox is 0-100 on both axes with preserveAspectRatio="none", so x/y are
  // effectively percentages of the container -- the arc scales with the
  // section instead of needing the node positions measured. non-scaling-stroke
  // keeps the line from being stretched into a wedge by that distortion.
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 hidden h-full w-full lg:block"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
    >
      <motion.path
        d="M 50 96 C 24 95, 5 82, 5 55 C 5 30, 24 13, 50 11"
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={1.25}
        strokeDasharray="4 4"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        opacity={0.28}
        initial={{ pathLength: 0 }}
        whileInView={{ pathLength: 1 }}
        viewport={{ once: true, amount: 0.5 }}
        transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
      />
      {active && !reduceMotion && (
        <motion.path
          d="M 50 96 C 24 95, 5 82, 5 55 C 5 30, 24 13, 50 11"
          fill="none"
          stroke="var(--color-accent-hover)"
          strokeWidth={1.25}
          strokeDasharray="4 12"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          opacity={0.5}
          animate={{ strokeDashoffset: [0, -32] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "linear" }}
        />
      )}
    </svg>
  );
}

function MetricChip({ metric, state }: { metric: string; state: StageState }) {
  return (
    <span
      className={`mt-2 inline-flex items-center rounded-md border px-2 py-1 font-mono-tabular text-[11px] transition-colors duration-300 ${
        state === "pending"
          ? "border-border text-text-faint"
          : "border-accent/30 bg-accent-soft/40 text-accent-text"
      }`}
    >
      {metric}
    </span>
  );
}

function StageContent({ stage, state, align }: { stage: Stage; state: StageState; align: "left" | "right" }) {
  const dimmed = state === "pending";
  return (
    <motion.div
      className={align === "right" ? "text-right" : ""}
      // Transform/opacity/filter only -- never layout properties. The faint
      // blur on upcoming stages reads as depth-of-field rather than "disabled".
      animate={{
        opacity: dimmed ? 0.42 : 1,
        scale: state === "active" ? 1 : 0.985,
        filter: dimmed ? "blur(0.8px)" : "blur(0px)",
      }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
    >
      <span
        className={`font-display text-lg font-semibold transition-colors duration-300 ${
          state === "pending" ? "text-text-faint" : "text-text"
        }`}
      >
        {stage.label}
      </span>
      <p className={`max-w-md pt-1.5 text-sm leading-relaxed text-text-muted ${align === "right" ? "ml-auto" : ""}`}>
        {stage.detail}
      </p>
      <div className={align === "right" ? "flex justify-end" : ""}>
        <MetricChip metric={stage.metric} state={state} />
      </div>
    </motion.div>
  );
}

function StageNode({ stage, index, state, reduceMotion }: { stage: Stage; index: number; state: StageState; reduceMotion: boolean }) {
  const { Icon } = stage;
  const isActive = state === "active";
  const isDone = state === "done";

  return (
    <motion.span
      className="absolute top-3 left-5 z-10 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border-2 sm:left-1/2"
      animate={{
        borderColor: isActive || isDone ? "var(--color-accent)" : "var(--color-border-strong)",
        backgroundColor: isDone ? "var(--color-accent)" : "var(--color-bg)",
        scale: isActive ? 1.12 : 1,
      }}
      transition={{ type: "spring", stiffness: 260, damping: 22 }}
    >
      {/* Breathing halo -- replaces animate-ping. Two offset layers on a slow
          spring read as a live "processing" state rather than a notification. */}
      {isActive && !reduceMotion && (
        <>
          <motion.span
            aria-hidden
            className="absolute inset-0 rounded-full bg-accent/25"
            animate={{ scale: [1, 1.85], opacity: [0.5, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }}
          />
          <motion.span
            aria-hidden
            className="absolute inset-0 rounded-full bg-accent/20"
            animate={{ scale: [1, 1.85], opacity: [0.4, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeOut", delay: 1 }}
          />
        </>
      )}
      {isActive && (
        <motion.span
          aria-hidden
          className="absolute inset-0 rounded-full"
          style={{ boxShadow: "0 0 18px 2px rgb(61 116 240 / 0.45)" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      )}

      <Icon
        size={15}
        strokeWidth={2}
        className={`relative transition-colors duration-300 ${
          isDone ? "text-bg" : isActive ? "text-accent-text" : "text-text-faint"
        }`}
      />
      <span className="sr-only">
        Stage {index + 1}: {stage.label}
      </span>
    </motion.span>
  );
}

function StageRow({
  stage,
  index,
  onRight,
  state,
  onActivate,
  reduceMotion,
}: {
  stage: Stage;
  index: number;
  onRight: boolean;
  state: StageState;
  onActivate: (i: number) => void;
  reduceMotion: boolean;
}) {
  const ref = useRef<HTMLLIElement>(null);
  // Narrow activation band: the row's top edge crossing ~45% of the viewport.
  // Deliberately tight so only one row qualifies at a time (last-wins is
  // harmless between two adjacent rows), and symmetric so scrolling back up
  // re-activates the previous stage rather than leaving everything "done".
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.58", "start 0.36"] });

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    if (v > 0 && v < 1) onActivate(index);
  });

  return (
    <motion.li
      ref={ref}
      className="relative py-3 pl-14 sm:flex sm:items-start sm:pl-0"
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.4 }}
      transition={{ duration: 0.45, delay: reduceMotion ? 0 : Math.min(index, 4) * 0.04, ease: [0.22, 1, 0.36, 1] }}
    >
      <StageNode stage={stage} index={index} state={state} reduceMotion={reduceMotion} />

      {/* Mobile: single column, always left-aligned (no side alternation). */}
      <div className="sm:hidden">
        <StageContent stage={stage} state={state} align="left" />
      </div>

      {/* Desktop: two ALWAYS-present halves, content only in the matching
          one -- guarantees the side, no auto-placement involved. */}
      <div className="hidden sm:block sm:w-1/2 sm:pr-12">
        {!onRight && <StageContent stage={stage} state={state} align="right" />}
      </div>
      <div className="hidden sm:block sm:w-1/2 sm:pl-12">
        {onRight && <StageContent stage={stage} state={state} align="left" />}
      </div>
    </motion.li>
  );
}
