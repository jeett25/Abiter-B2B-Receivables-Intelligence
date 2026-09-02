// Shared design-system primitives for the console. Migrated (2026-09-02)
// from the Day-6 Phase-C v1 pill/soft-badge look to the current "control
// room" language established on the landing page: rectangular tracked-caps
// mono tags instead of pill badges, the refined radius scale
// (rounded-tag/control/card/panel), font-display for real headings. Tailwind
// utility classes reference the CSS custom properties in app/globals.css's
// @theme block -- change the palette there, not here.

import type { LucideIcon } from "lucide-react";
import { ReactNode } from "react";
import { AccountCurrentState, ActionType, PolicyResult } from "./types";

export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function formatCurrency(value: number): string {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

// ---------------------------------------------------------------------------
// Status semantics -- one source of truth for what color/label every real
// account_state / action_type / policy_result maps to across the console.
// ---------------------------------------------------------------------------

type StatusTone = "wait" | "remind" | "escalate" | "dispute" | "success" | "danger" | "neutral";

const STATE_META: Record<AccountCurrentState, { label: string; tone: StatusTone }> = {
  overdue: { label: "Overdue", tone: "neutral" },
  assessment: { label: "Assessment", tone: "neutral" },
  wait: { label: "Wait", tone: "wait" },
  remind: { label: "Remind", tone: "remind" },
  escalate: { label: "Escalate", tone: "escalate" },
  promise: { label: "Promise", tone: "remind" },
  monitoring: { label: "Monitoring", tone: "wait" },
  kept: { label: "Kept", tone: "success" },
  broken: { label: "Broken", tone: "danger" },
  reassess: { label: "Reassess", tone: "escalate" },
  closed: { label: "Closed", tone: "neutral" },
  closed_paid: { label: "Closed · Paid", tone: "success" },
  closed_abandoned: { label: "Closed · Abandoned", tone: "danger" },
  dispute_review: { label: "Dispute Review", tone: "dispute" },
};

const ACTION_META: Record<ActionType, { label: string; tone: StatusTone }> = {
  wait: { label: "Wait", tone: "wait" },
  email: { label: "Email", tone: "remind" },
  whatsapp: { label: "WhatsApp", tone: "remind" },
  payment_link: { label: "Payment Link", tone: "remind" },
  voice: { label: "Voice Call", tone: "escalate" },
  escalate: { label: "Escalate", tone: "escalate" },
  stop: { label: "Stop", tone: "neutral" },
};

const POLICY_META: Record<PolicyResult, { label: string; tone: StatusTone }> = {
  allowed: { label: "Allowed", tone: "success" },
  blocked: { label: "Blocked", tone: "danger" },
  escalated: { label: "Escalated", tone: "escalate" },
};

const TONE_CLASSES: Record<StatusTone, string> = {
  wait: "bg-status-wait-soft text-status-wait border-status-wait/30",
  remind: "bg-status-remind-soft text-status-remind border-status-remind/30",
  escalate: "bg-status-escalate-soft text-status-escalate border-status-escalate/30",
  dispute: "bg-status-dispute-soft text-status-dispute border-status-dispute/30",
  success: "bg-status-success-soft text-status-success border-status-success/30",
  danger: "bg-status-danger-soft text-status-danger border-status-danger/30",
  neutral: "bg-surface-2 text-text-muted border-border-strong",
};

const TONE_DOT: Record<StatusTone, string> = {
  wait: "bg-status-wait",
  remind: "bg-status-remind",
  escalate: "bg-status-escalate",
  dispute: "bg-status-dispute",
  success: "bg-status-success",
  danger: "bg-status-danger",
  neutral: "bg-text-faint",
};

export function stateMeta(state: AccountCurrentState) {
  return STATE_META[state] ?? { label: state, tone: "neutral" as StatusTone };
}
export function actionMeta(action: ActionType) {
  return ACTION_META[action] ?? { label: action, tone: "neutral" as StatusTone };
}
export function policyMeta(result: PolicyResult) {
  return POLICY_META[result] ?? { label: result, tone: "neutral" as StatusTone };
}

// Rectangular tracked-caps mono tag -- replaces the earlier soft pill.
// Matches the "control room" meta-text treatment used everywhere on the
// landing page (badges/nav/labels), so a status marker in the console reads
// as the same visual language, not a leftover from the old design pass.
export function Badge({ tone, children, dot = true }: { tone: StatusTone; children: ReactNode; dot?: boolean }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-[var(--radius-tag)] border px-2 py-1 font-mono text-[10.5px] font-medium tracking-wider whitespace-nowrap uppercase",
        TONE_CLASSES[tone]
      )}
    >
      {dot && <span className={cx("h-1.5 w-1.5 rounded-full", TONE_DOT[tone])} />}
      {children}
    </span>
  );
}

export function StateBadge({ state }: { state: AccountCurrentState }) {
  const m = stateMeta(state);
  return <Badge tone={m.tone}>{m.label}</Badge>;
}
export function ActionBadge({ action }: { action: ActionType | null }) {
  if (!action) return <span className="text-text-faint">—</span>;
  const m = actionMeta(action);
  return <Badge tone={m.tone}>{m.label}</Badge>;
}
export function PolicyBadge({ result }: { result: PolicyResult | null | undefined }) {
  if (!result) return <span className="text-text-faint">n/a</span>;
  const m = policyMeta(result);
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

// ---------------------------------------------------------------------------
// Layout primitives
// ---------------------------------------------------------------------------

export function Card({ children, className, id }: { children: ReactNode; className?: string; id?: string }) {
  return (
    <div id={id} className={cx("rounded-card border border-border bg-surface/80 shadow-soft backdrop-blur-sm scroll-mt-24", className)}>
      {children}
    </div>
  );
}

export function SectionCard({
  id,
  index,
  title,
  children,
  className,
}: {
  id?: string;
  index?: number;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cx("scroll-mt-24", className)}>
      <Card className="p-5 sm:p-6">
        <h2 className="label mb-4 flex items-center gap-2.5 text-text-muted">
          {typeof index === "number" && (
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono text-[11px] text-accent-text normal-case">
              {index}
            </span>
          )}
          {title}
        </h2>
        {children}
      </Card>
    </section>
  );
}

const TILE_VALUE_CLASSES: Record<"neutral" | "success" | "danger" | "accent", string> = {
  neutral: "text-text",
  success: "text-status-success",
  danger: "text-status-danger",
  accent: "text-accent-text",
};

export function StatTile({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "success" | "danger" | "accent";
}) {
  return (
    <div className="rounded-card border border-border bg-surface-2/60 p-4">
      <div className="label">{label}</div>
      <div className={cx("mt-1.5 font-mono-tabular text-2xl font-semibold", TILE_VALUE_CLASSES[tone])}>{value}</div>
      {sub && <div className="mt-1 text-xs text-text-faint">{sub}</div>}
    </div>
  );
}

// Icon-badged stat tile -- built for the metrics page's KPI row, promoted
// here once the observability page needed the exact same pattern. Distinct
// from StatTile above (no icon, tighter): use IconStat when a lucide icon
// adds real scannability to a row of several tiles, StatTile for a plain
// label/value pair elsewhere.
type IconStatTone = "accent" | "success" | "danger" | "neutral";

const ICON_STAT_ICON_TONE: Record<IconStatTone, string> = {
  accent: "bg-accent-soft text-accent-text",
  success: "bg-status-success-soft text-status-success",
  danger: "bg-status-danger-soft text-status-danger",
  neutral: "bg-surface-2 text-text-muted",
};
const ICON_STAT_VALUE_TONE: Record<IconStatTone, string> = {
  accent: "text-accent-text",
  success: "text-status-success",
  danger: "text-status-danger",
  neutral: "text-text",
};

// tone should reflect the VALUE's actual sign/meaning, never hardcoded --
// a metric that can legitimately go negative (e.g. incremental recovery)
// must compute its tone from the number, not assume "success" because the
// tile usually looks good. See signTone() below for the common case.
export function IconStat({
  icon: Icon,
  label,
  value,
  sub,
  tone = "neutral",
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  tone?: IconStatTone;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center gap-2.5">
        <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-control)]", ICON_STAT_ICON_TONE[tone])}>
          <Icon size={15} strokeWidth={1.75} />
        </span>
        <div className="label !text-text-muted">{label}</div>
      </div>
      <div className={cx("mt-3 font-mono-tabular text-2xl font-semibold", ICON_STAT_VALUE_TONE[tone])}>{value}</div>
      {sub && <div className="mt-1 text-xs text-text-faint">{sub}</div>}
    </Card>
  );
}

export function signTone(value: number): "success" | "danger" {
  return value >= 0 ? "success" : "danger";
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-text">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-sm text-text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </div>
  );
}

export function ErrorPanel({ message, retryHref }: { message: string; retryHref: string }) {
  return (
    <Card className="border-status-danger/30 bg-status-danger-soft/40 p-6">
      <p role="alert" className="text-sm text-status-danger">
        {message}
      </p>
      <a
        href={retryHref}
        className="mt-3 inline-block rounded-[var(--radius-control)] border border-status-danger/40 px-3 py-1.5 text-sm font-medium text-status-danger transition-colors hover:bg-status-danger-soft"
      >
        Retry
      </a>
    </Card>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-card border border-dashed border-border-strong p-10 text-center text-sm text-text-faint">
      {children}
    </div>
  );
}
