"use client";

import { Fingerprint, Mail, MessageCircleQuestion } from "lucide-react";
import { motion } from "framer-motion";
import type { ComponentType } from "react";

// Rebuilt again (2026-09-02) -- dropped the bar-comparison diagrams
// entirely per feedback ("no point of them"). Each problem now gets one
// large icon badge instead: a glowing circular mark with a soft pulse ring
// and (for problem 1 specifically) a small scatter of faded duplicate
// icons behind it, standing in for "blasted to everyone indiscriminately."
// No stock imagery -- this session has no way to fetch real image bytes
// from the web (only text extraction), so this leans on icon composition
// instead of a downloaded photo/illustration.

function IconBadge({
  Icon,
  color,
  glow,
  scatter,
}: {
  Icon: ComponentType<{ size?: number; className?: string }>;
  color: string;
  glow: string;
  scatter?: boolean;
}) {
  return (
    <div className="relative flex h-32 items-center justify-center sm:h-36">
      {scatter &&
        [
          { x: -46, y: -8, r: -18, s: 0.55, d: 0 },
          { x: 40, y: -26, r: 14, s: 0.5, d: 0.05 },
          { x: 50, y: 22, r: 22, s: 0.6, d: 0.1 },
          { x: -38, y: 30, r: -12, s: 0.5, d: 0.15 },
        ].map((p, i) => (
          <motion.span
            key={i}
            className="absolute text-text-faint/30"
            style={{ x: p.x, y: p.y, rotate: p.r }}
            initial={{ opacity: 0, scale: 0 }}
            whileInView={{ opacity: 1, scale: p.s }}
            viewport={{ once: true, amount: 0.8 }}
            transition={{ duration: 0.4, delay: p.d }}
          >
            <Mail size={30} />
          </motion.span>
        ))}

      <motion.div
        className="relative flex h-20 w-20 items-center justify-center rounded-full sm:h-24 sm:w-24"
        style={{ background: glow }}
        initial={{ scale: 0, opacity: 0 }}
        whileInView={{ scale: 1, opacity: 1 }}
        viewport={{ once: true, amount: 0.8 }}
        transition={{ type: "spring", stiffness: 220, damping: 20 }}
      >
        <motion.span
          className="absolute inset-0 rounded-full"
          style={{ boxShadow: `0 0 0 1px ${color}55` }}
          animate={{ scale: [1, 1.35, 1], opacity: [0.5, 0, 0.5] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        />
        <span className="relative" style={{ color }}>
          <Icon size={32} />
        </span>
      </motion.div>
    </div>
  );
}

export function WastedSpendVisual() {
  return (
    <IconBadge
      Icon={Mail}
      color="var(--color-status-danger)"
      glow="radial-gradient(circle, rgb(234 90 99 / 0.22), rgb(234 90 99 / 0.05))"
      scatter
    />
  );
}

export function ConfidenceMeterVisual() {
  return (
    <IconBadge
      Icon={MessageCircleQuestion}
      color="var(--color-accent)"
      glow="radial-gradient(circle, rgb(61 116 240 / 0.22), rgb(61 116 240 / 0.05))"
    />
  );
}

export function NoiseVsSignalVisual() {
  return (
    <IconBadge
      Icon={Fingerprint}
      color="var(--color-status-success)"
      glow="radial-gradient(circle, rgb(53 193 147 / 0.22), rgb(53 193 147 / 0.05))"
    />
  );
}
