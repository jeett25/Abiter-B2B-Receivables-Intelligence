// Shared design-system primitives for the console (Phase C, subtask 11).
// Tailwind utility classes reference the CSS custom properties defined in
// app/globals.css's @theme block -- change the palette there, not here.

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

export function Badge({ tone, children, dot = true }: { tone: StatusTone; children: ReactNode; dot?: boolean }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium whitespace-nowrap",
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

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "rounded-2xl border border-border bg-surface/80 backdrop-blur-sm shadow-soft",
        className
      )}
    >
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
        <h2 className="flex items-center gap-2.5 text-sm font-semibold tracking-wide text-text-muted uppercase mb-4">
          {typeof index === "number" && (
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent-text text-[11px] font-mono-tabular normal-case">
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
    <div className="rounded-xl border border-border bg-surface-2/60 p-4">
      <div className="text-xs font-medium text-text-muted uppercase tracking-wide">{label}</div>
      <div className={cx("mt-1.5 text-2xl font-semibold font-mono-tabular", TILE_VALUE_CLASSES[tone])}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-text-faint">{sub}</div>}
    </div>
  );
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
        <h1 className="text-2xl font-semibold tracking-tight text-text">{title}</h1>
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
        className="mt-3 inline-block rounded-lg border border-status-danger/40 px-3 py-1.5 text-sm font-medium text-status-danger hover:bg-status-danger-soft transition-colors"
      >
        Retry
      </a>
    </Card>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border-strong p-10 text-center text-sm text-text-faint">
      {children}
    </div>
  );
}
