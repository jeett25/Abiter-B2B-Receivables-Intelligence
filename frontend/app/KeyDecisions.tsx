"use client";

import { FlaskConical, History, Scale, ShieldCheck } from "lucide-react";
import { motion } from "framer-motion";
import type { ComponentType } from "react";

// Full redesign (2026-09-02) -- the previous version was a plain stacked
// log list, visually indistinguishable from a bullet list. This is
// deliberately the most "designed" section on the page: each decision gets
// its own icon and semantic accent color (reusing existing status tokens,
// not inventing a new palette) so the grid reads as a set of distinct
// claims, not four paragraphs of the same shape.

const ITEMS: {
  tag: string;
  title: string;
  body: string;
  icon: ComponentType<{ size?: number | string; className?: string }>;
  tone: "accent" | "remind" | "escalate" | "success";
}[] = [
  {
    tag: "policy",
    title: "No LLM chooses the action",
    body: "The Economics Engine and a deterministic Policy/Safety Gate make every decision. The only LLM call extracts a payment promise from a customer's message — it never influences recovery scoring, economics, or policy.",
    icon: Scale,
    tone: "accent",
  },
  {
    tag: "measurement",
    title: "Attribution over vanity metrics",
    body: "A randomized holdout (treatment vs. control) measures real incremental recovery, not \"we sent more messages.\" The experiment corrects the Economics Engine's own uplift assumptions against what was actually observed.",
    icon: FlaskConical,
    tone: "remind",
  },
  {
    tag: "safety",
    title: "The policy gate is a hard boundary",
    body: "8 fixed-priority rules — already-paid (cross-referenced against the real ledger), disputes, contact caps, cooldowns, business hours, human-approval routing for large escalations — sit between the model and any real action.",
    icon: ShieldCheck,
    tone: "escalate",
  },
  {
    tag: "integrity",
    title: "Every score is point-in-time safe",
    body: "Recovery and promise-to-pay models are scored strictly as of a cutoff — no feature is ever computed using information that wouldn't have existed yet. Verified with adversarial future-leakage tests, not just asserted.",
    icon: History,
    tone: "success",
  },
];

const TONE_STYLES: Record<string, { text: string; bg: string; border: string; ring: string }> = {
  accent: { text: "text-accent-text", bg: "bg-accent-soft", border: "hover:border-accent/40", ring: "group-hover:shadow-[0_0_0_1px_rgb(61_116_240/0.35),0_16px_40px_-16px_rgb(61_116_240/0.5)]" },
  remind: { text: "text-status-remind", bg: "bg-status-remind-soft", border: "hover:border-status-remind/40", ring: "group-hover:shadow-[0_0_0_1px_rgb(56_189_248/0.35),0_16px_40px_-16px_rgb(56_189_248/0.5)]" },
  escalate: { text: "text-status-escalate", bg: "bg-status-escalate-soft", border: "hover:border-status-escalate/40", ring: "group-hover:shadow-[0_0_0_1px_rgb(226_160_63/0.35),0_16px_40px_-16px_rgb(226_160_63/0.5)]" },
  success: { text: "text-status-success", bg: "bg-status-success-soft", border: "hover:border-status-success/40", ring: "group-hover:shadow-[0_0_0_1px_rgb(53_193_147/0.35),0_16px_40px_-16px_rgb(53_193_147/0.5)]" },
};

export default function KeyDecisions() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {ITEMS.map((item, i) => {
        const tone = TONE_STYLES[item.tone];
        const Icon = item.icon;
        return (
          <motion.div
            key={item.tag}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.4 }}
            transition={{ duration: 0.45, delay: i * 0.08, ease: [0.22, 1, 0.36, 1] }}
            className={`group relative rounded-panel border border-border bg-surface/60 p-6 transition-all duration-300 hover:-translate-y-1 ${tone.border} ${tone.ring}`}
          >
            <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${tone.bg}`}>
              <Icon size={20} className={tone.text} />
            </div>
            <div className="label mt-4 text-text-faint">{item.tag}</div>
            <div className="mt-1.5 font-display text-lg font-semibold text-text">{item.title}</div>
            <p className="mt-2 text-sm leading-relaxed text-text-muted">{item.body}</p>
          </motion.div>
        );
      })}
    </div>
  );
}
