import Link from "next/link";
import { notFound } from "next/navigation";
import {
  AlarmClock,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Gavel,
  MinusCircle,
  Receipt,
  Scale,
  ShieldQuestion,
  Wallet,
  XCircle,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { ApiError, getDecision, getDemoFixtures, getInvoice, getTimeline } from "@/lib/api";
import { ActionEV, DecisionTrace, DemoFixture, InvoiceSummary, InvoiceTimeline } from "@/lib/types";
import { ActionBadge, Badge, Card, ErrorPanel, PolicyBadge, StateBadge, formatCurrency, formatPercent } from "@/lib/ui";
import RefreshButton from "../../RefreshButton";
import RadialGauge from "../../RadialGauge";
import DemoScenarioBanner from "./DemoScenarioBanner";
import SimilarCasesCard from "./SimilarCasesCard";

// Second redesign pass (2026-09-02): consolidated the hero into one line,
// dropped the jump-link nav (not needed once the page reads top to bottom
// without a fixed header competing for space), condensed "Why this
// decision" into three flex-width segments instead of stacked paragraphs,
// Action Economics + Policy Gate now sit side by side (reference-inspired),
// and the trailing four sections (cases/safety/LLM/timeline) are grouped
// into two columns instead of one long stack of full-width cards.

function getStateTransitionPath(detail: Record<string, unknown>): string[] | null {
  const path = detail.state_transition_path;
  if (!Array.isArray(path) || path.length === 0) return null;
  if (!path.every((s) => typeof s === "string")) return null;
  return path as string[];
}

function daysOverdue(dueDate: string): number {
  const due = new Date(dueDate);
  const now = new Date();
  return Math.max(0, Math.round((now.getTime() - due.getTime()) / (1000 * 60 * 60 * 24)));
}

const JUMP_LINKS = [
  { href: "#economics", label: "Economics" },
  { href: "#policy-check", label: "Policy gate" },
  { href: "#cases", label: "Similar cases" },
  { href: "#safety", label: "Safety & failures" },
  { href: "#llm-extraction", label: "LLM extraction" },
  { href: "#timeline", label: "Timeline" },
];

// The ₹ glyph renders visibly larger than digits in the mono/display faces
// this project uses -- most noticeable at large sizes (the hero amount).
// Rendered at 0.6em relative to its own number instead of matching it 1:1.
function Currency({ value, className }: { value: number; className?: string }) {
  return (
    <span className={className}>
      <span className="mr-0.5 text-[0.6em]">₹</span>
      {value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
    </span>
  );
}

export default async function DecisionTracePage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = await params;

  let invoice: InvoiceSummary, trace: DecisionTrace, timeline: InvoiceTimeline;
  try {
    [invoice, trace, timeline] = await Promise.all([getInvoice(invoiceId), getDecision(invoiceId), getTimeline(invoiceId)]);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    const message = err instanceof ApiError ? err.message : "Unexpected error loading this invoice.";
    return (
      <div>
        <BackLink />
        <ErrorPanel message={`Failed to load invoice ${invoiceId}: ${message}`} retryHref={`/invoices/${invoiceId}`} />
      </div>
    );
  }

  const candidateActions = trace.model_scores.candidate_actions ?? [];
  const retrievedCases = trace.evidence.retrieved_cases ?? [];
  const sortedCandidates = [...candidateActions].sort((a, b) => b.expected_value - a.expected_value);
  // "Recommended" means what the Economics Engine actually recommends
  // (proposed_action, its own post-materiality-check answer), not just
  // whichever row happens to have the highest raw net value -- those two
  // can differ when the top row's edge over Wait is too small to be worth
  // acting on. Falls back to the top row only if proposed_action is
  // missing (older/legacy decision_logs shape).
  const recommendedAction = trace.policy_checks.proposed_action ?? sortedCandidates[0]?.action_type;
  const recommendedCandidate = sortedCandidates.find((c) => c.action_type === recommendedAction);
  const topCandidate = sortedCandidates[0];
  const recommendationDivertsFromTop = Boolean(
    recommendedCandidate && topCandidate && recommendedCandidate.action_type !== topCandidate.action_type
  );
  const selectedAction = trace.policy_checks.selected_action ?? trace.policy_checks.final_action;
  const policyResult = trace.policy_checks.policy_result ?? trace.policy_checks.result;
  const overdue = daysOverdue(invoice.due_date);
  const hasAnyGauge = trace.model_scores.recovery_probability !== null || trace.model_scores.ptp_probability !== null;

  // Same graceful-degradation precedent as layout.tsx's own getDemoFixtures()
  // call -- this banner is a nice-to-have, never worth breaking the whole
  // page over a backend hiccup.
  let demoFixture: DemoFixture | undefined;
  try {
    const fixtures = await getDemoFixtures();
    demoFixture = fixtures.find((f) => f.invoice_id === invoiceId);
  } catch {
    demoFixture = undefined;
  }

  return (
    <div className="space-y-5">
      <BackLink />
      <DemoScenarioBanner fixture={demoFixture} />

      {/* ================= Hero -- restored to the stacked layout + jump-link
          nav (the "one line" version read badly; this keeps the Currency
          ₹-sizing fix but reverts the structure). ================= */}
      <Card className="relative overflow-hidden p-6 sm:p-8">
        <div aria-hidden className="section-glow" style={{ "--glow-x": "20%" } as CSSProperties} />
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge tone="neutral" dot={false}>
                {trace.invoice_number}
              </Badge>
              {invoice.treatment_group && (
                <Badge tone="neutral" dot={false}>
                  Attribution: {invoice.treatment_group}
                </Badge>
              )}
            </div>
            <h1 className="font-display text-3xl font-semibold tracking-tight text-text sm:text-4xl">{trace.customer_name}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <StateBadge state={invoice.current_state} />
              <span className="text-sm text-text-faint">Due {invoice.due_date}</span>
            </div>
          </div>

          <div className="flex items-start gap-8 text-right">
            <div>
              <div className="label">Amount</div>
              <Currency value={trace.amount} className="font-mono-tabular text-2xl font-semibold text-text sm:text-3xl" />
            </div>
            {overdue > 0 && (
              <div>
                <div className="label">Overdue</div>
                <div className="font-mono-tabular text-2xl font-semibold text-status-danger sm:text-3xl">{overdue}d</div>
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-4 text-sm text-text-muted">
          {JUMP_LINKS.map((l) => (
            <a key={l.href} href={l.href} className="transition-colors hover:text-accent-text">
              {l.label}
            </a>
          ))}
          <div className="ml-auto">
            <RefreshButton />
          </div>
        </div>
      </Card>

      {/* ================= Why this decision / Predictive models / Why at
          risk -- one row, three content-sized columns (not equal thirds:
          "why this decision" is short text, the gauge needs less width
          than the 3-card signal grid). ================= */}
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_1.6fr]">
        <Card className="border-accent/25 bg-accent-soft/40 p-5 sm:p-6">
          <div className="label text-accent-text">Why this decision?</div>
          <p className="mt-2 text-base font-medium text-text">
            Chose <span className="text-accent-text">{trace.decision}</span>
          </p>
          <p className="mt-1.5 text-sm text-text-muted">{trace.reason}</p>
          {trace.assessed_at && (
            <p className="mt-2.5 border-t border-accent/20 pt-2.5 text-xs text-text-faint">
              Predictive scores, action economics, and similar cases below are from the last live assessment,{" "}
              {new Date(trace.assessed_at).toLocaleString("en-IN")} — made before this outcome was recorded.
            </p>
          )}
        </Card>

        <Card className="p-5 sm:p-6">
          <div className="label mb-4 !text-text-muted">Predictive models</div>
          {hasAnyGauge ? (
            <div className="flex items-center justify-center gap-6">
              {trace.model_scores.recovery_probability !== null && (
                <RadialGauge value={trace.model_scores.recovery_probability} label="Recovery" color="var(--color-accent)" />
              )}
              {trace.model_scores.ptp_probability !== null && (
                <RadialGauge value={trace.model_scores.ptp_probability} label="Promise-to-pay" color="var(--color-status-escalate)" />
              )}
            </div>
          ) : (
            <EmptyPanel title="No predictive score recorded for this round." />
          )}
          <RootCauseRow rootCause={trace.model_scores.root_cause} isDisputed={trace.policy_checks.is_disputed} />
        </Card>

        <Card className="p-5 sm:p-6">
          <div className="label mb-4 !text-text-muted">Why this needs attention</div>
          <div className="grid gap-3 sm:grid-cols-3">
            <SignalCard
              icon={trace.policy_checks.is_disputed ? AlertTriangle : CheckCircle2}
              tone={trace.policy_checks.is_disputed ? "danger" : "success"}
              title={trace.policy_checks.is_disputed ? "Disputed" : "No dispute"}
              detail={
                trace.policy_checks.is_disputed
                  ? "Collections pressure withheld pending resolution."
                  : "Root cause not flagged as a dispute."
              }
            />
            <SignalCard
              icon={trace.policy_checks.is_actually_paid ? CheckCircle2 : Clock}
              tone={trace.policy_checks.is_actually_paid ? "success" : "neutral"}
              title={trace.policy_checks.is_actually_paid ? "Already paid" : "Not yet paid"}
              detail={
                trace.policy_checks.is_actually_paid
                  ? "Ledger shows payment — status pending reconciliation."
                  : "Cross-referenced directly against the payments ledger."
              }
            />
            <SignalCard
              icon={ShieldQuestion}
              tone={
                trace.model_scores.recovery_probability === null
                  ? "neutral"
                  : trace.model_scores.recovery_probability >= 0.65
                    ? "success"
                    : trace.model_scores.recovery_probability >= 0.35
                      ? "escalate"
                      : "danger"
              }
              title="Recovery signal"
              detail={
                trace.model_scores.recovery_probability === null
                  ? "No score for this round."
                  : trace.model_scores.recovery_probability >= 0.65
                    ? "High — organic recovery likely."
                    : trace.model_scores.recovery_probability >= 0.35
                      ? "Medium — worth a targeted nudge."
                      : "Low — needs an assertive channel."
              }
            />
          </div>
        </Card>
      </div>

      {/* ================= Action economics + Policy gate, side by side --
          switched lg: (1024px) to md: (768px): at lg the pair was still
          stacking on realistic window widths. Also tightened padding/type
          size on both so they comfortably share a row rather than needing
          the full viewport width to avoid a squeeze. ================= */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card id="economics" className="p-4 sm:p-5 md:col-span-3">
          <div className="mb-3 flex items-center justify-between">
            <div className="label !text-text-muted">Candidate-action economics</div>
            {recommendedAction && <Badge tone="remind">Recommended: {recommendedAction}</Badge>}
          </div>
          {sortedCandidates.length === 0 ? (
            <EmptyPanel title="No candidate-action comparison recorded for this round." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="label px-2 py-1.5 !text-[9px] !text-text-faint">Channel</th>
                    <th className="label px-2 py-1.5 text-right !text-[9px] !text-text-faint">Recovery %</th>
                    <th className="label px-2 py-1.5 text-right !text-[9px] !text-text-faint">Cost</th>
                    <th className="label px-2 py-1.5 text-right !text-[9px] !text-text-faint">Friction</th>
                    <th className="label px-2 py-1.5 text-right !text-[9px] !text-text-faint">Net value</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCandidates.map((candidate) => (
                    <EvRow key={candidate.action_type} candidate={candidate} isRecommended={candidate.action_type === recommendedAction} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {recommendationDivertsFromTop && topCandidate && recommendedCandidate && (
            <div className="mt-3 rounded-card border border-status-escalate/30 bg-status-escalate-soft/40 p-3 text-xs text-text">
              Even though <ActionBadge action={topCandidate.action_type} /> nets more (
              <span className="font-mono-tabular text-status-success">{formatCurrency(topCandidate.expected_value)}</span> vs.{" "}
              <span className="font-mono-tabular">{formatCurrency(recommendedCandidate.expected_value)}</span>), the system recommends{" "}
              <ActionBadge action={recommendedCandidate.action_type} /> instead — the edge isn&rsquo;t large enough relative to the
              invoice amount to justify the added cost and friction of intervening.
            </div>
          )}
        </Card>

        <Card id="policy-check" className="p-4 sm:p-5 md:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <div className="label !text-text-muted">Policy gate</div>
            <PolicyBadge result={policyResult} />
          </div>
          <PolicyChecklist trace={trace} policyResult={policyResult} />
          <p className="mt-3 border-t border-border pt-2.5 text-xs text-text-muted">{trace.reason}</p>
          {trace.policy_checks.proposed_action && selectedAction && trace.policy_checks.proposed_action !== selectedAction && (
            <p className="mt-2 text-xs text-text">
              Proposed <ActionBadge action={trace.policy_checks.proposed_action} />{" "}
              {policyResult === "allowed" ? (
                <>
                  fell back to <ActionBadge action={selectedAction} /> after a tool failure.
                </>
              ) : (
                <>
                  overridden to <ActionBadge action={selectedAction} /> by policy.
                </>
              )}
            </p>
          )}
          <div className="mt-3 flex items-center gap-2.5 border-t border-border pt-3">
            <span className="text-xs text-text-muted">Chosen:</span>
            <ActionBadge action={selectedAction ?? null} />
          </div>
        </Card>
      </div>

      {/* ================= Cases / Safety+LLM / Timeline -- 3 columns now,
          not 4. Safety and LLM extraction are both short/sparse content
          (confirmed by the real screenshot: mostly empty space below their
          text at 1/4 width) -- stacked together in the middle column
          instead, so Similar Cases and Timeline (the two with genuinely
          substantial content) each get more width. ================= */}
      <div className="grid gap-4 lg:grid-cols-[1fr_0.85fr_1.15fr]">
        <Card id="cases" className="p-4 sm:p-5">
          <div className="label mb-3 !text-text-muted">Similar past cases</div>
          <SimilarCasesCard cases={retrievedCases} />
        </Card>

        {/* flex-col + flex-1 on each card so the two of them together fill
            the SAME total height as Cases/Timeline (grid's default
            align-items:stretch already stretches this wrapper to match the
            row -- flex-1 is what makes the two cards actually share that
            extra height instead of leaving empty space below them). */}
        <div className="flex flex-col gap-4">
          <Card id="safety" className="flex-1 p-4 sm:p-5">
            <div className="label mb-3 !text-text-muted">Safety & failure handling</div>
            <SafetyList trace={trace} policyResult={policyResult} selectedAction={selectedAction} />
          </Card>

          <Card id="llm-extraction" className="flex-1 p-4 sm:p-5">
            <div className="label mb-3 !text-text-muted">LLM: promise extraction</div>
            <LlmExtraction trace={trace} />
          </Card>
        </div>

        <Card id="timeline" className="p-4 sm:p-5">
          <div className="label mb-3 !text-text-muted">Timeline</div>
          {timeline.events.length === 0 ? (
            <p className="text-sm text-text-muted">No recorded events for this invoice yet.</p>
          ) : (
            <ol className="relative max-h-80 space-y-4 overflow-y-auto border-l border-border pl-4">
              {timeline.events.map((event, i) => {
                const path = getStateTransitionPath(event.detail);
                // Only worth showing when it's an ACTUAL multi-step
                // transition (e.g. a real reassessment chain) -- a
                // single-item path is just the decision word repeated
                // right below itself.
                const showPath = path && path.length > 1;
                const EventIcon = event.type === "payment" ? Receipt : Gavel;
                return (
                  <li key={i} className="relative text-xs">
                    <span className="absolute -left-[19px] top-1 h-2 w-2 rounded-full bg-accent ring-4 ring-bg" />
                    <div className="font-mono-tabular text-text-faint">{new Date(event.timestamp).toLocaleString("en-IN")}</div>
                    <div className="mt-0.5 flex items-start gap-1.5 text-text">
                      <EventIcon size={12} className="mt-0.5 shrink-0 text-text-faint" aria-hidden />
                      <span>{event.summary}</span>
                    </div>
                    {showPath && <div className="mt-0.5 font-mono-tabular text-accent-text">{path.join(" → ")}</div>}
                  </li>
                );
              })}
            </ol>
          )}
        </Card>
      </div>
    </div>
  );
}

// Shared "nothing here, and that's expected" state -- an icon + a
// deliberately centered, modest block reads as "the system correctly has
// nothing to show" rather than a lonely sentence in an otherwise-empty
// card, which reads as broken. Reuses MinusCircle, the same icon this page
// already uses for RootCauseRow's own empty state, for visual consistency.
function EmptyPanel({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      <MinusCircle size={20} className="text-text-faint" />
      <p className="text-sm text-text-muted">{title}</p>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/invoices" className="inline-flex items-center gap-1.5 text-sm text-text-muted transition-colors hover:text-text">
      <ArrowLeft size={14} /> Back to invoices
    </Link>
  );
}

type SignalTone = "success" | "danger" | "escalate" | "neutral";
const SIGNAL_TONE_CLASSES: Record<SignalTone, string> = {
  success: "text-status-success bg-status-success-soft",
  danger: "text-status-danger bg-status-danger-soft",
  escalate: "text-status-escalate bg-status-escalate-soft",
  neutral: "text-text-faint bg-surface-2",
};

// app/ml/train_root_cause.py's classifier -- cash_flow_stress vs. oversight,
// non-disputed invoices only (see RootCauseScore's comment in lib/types.ts).
// Sits inside "Predictive models" rather than its own card/grid column: it
// IS a predictive model's output, and the existing gauges card already has
// the vertical room for one more compact row -- no grid/breakpoint changes
// needed elsewhere on the page.
const ROOT_CAUSE_COPY: Record<"cash_flow_stress" | "oversight", { label: string; icon: typeof Wallet; tone: SignalTone; why: string }> = {
  cash_flow_stress: {
    label: "Cash-flow stress",
    icon: Wallet,
    tone: "escalate",
    why: "Recent payment behavior + historical delay pattern",
  },
  oversight: {
    label: "Oversight",
    icon: AlarmClock,
    tone: "success",
    why: "No cash-flow signal — likely just missed",
  },
};

function RootCauseRow({
  rootCause,
  isDisputed,
}: {
  rootCause: DecisionTrace["model_scores"]["root_cause"];
  isDisputed: boolean | null;
}) {
  if (!rootCause) {
    return (
      <p className="mt-4 border-t border-border pt-3 text-center text-xs text-text-faint">
        {isDisputed ? "Root cause: not computed — invoice is disputed." : "Root cause: not available for this decision round."}
      </p>
    );
  }

  const copy = ROOT_CAUSE_COPY[rootCause.predicted_label];
  const Icon = copy.icon;
  return (
    <div className="mt-4 flex items-center gap-2.5 border-t border-border pt-3">
      <span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${SIGNAL_TONE_CLASSES[copy.tone]}`}>
        <Icon size={14} />
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-xs font-semibold text-text">Root cause: {copy.label}</span>
          <span className="font-mono-tabular text-[11px] text-text-muted">{formatPercent(rootCause.confidence)}</span>
        </div>
        <p className="mt-0.5 truncate text-[11px] text-text-faint">{copy.why}</p>
      </div>
    </div>
  );
}

function SignalCard({
  icon: Icon,
  tone,
  title,
  detail,
}: {
  icon: typeof AlertTriangle;
  tone: SignalTone;
  title: string;
  detail: string;
}) {
  return (
    <div className="rounded-card border border-border bg-surface-2/40 p-3.5">
      <div className="flex items-center gap-2.5">
        <span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${SIGNAL_TONE_CLASSES[tone]}`}>
          <Icon size={14} />
        </span>
        <span className="text-sm font-semibold text-text">{title}</span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-text-faint">{detail}</p>
    </div>
  );
}

// Bar color is tiered by this channel's own probability (65-100 green,
// 40-65 yellow, below that red) -- same scale as the invoices list's
// recoverability bar, applied here per-channel instead of net-value
// sign, per explicit request.
function probabilityTierColor(pct: number): string {
  if (pct >= 65) return "bg-status-success";
  if (pct >= 40) return "bg-status-escalate";
  return "bg-status-danger";
}

// "Recommended" is now the ONE row matching proposed_action (the Economics
// Engine's real, post-materiality-check answer) -- see recommendedAction's
// definition above. No more separate "top row" vs "proposed row" tags:
// when they're the same row (the common case) it's just highlighted; when
// they differ, the explanatory note above the table (in the parent) covers
// it in plain language instead of a cryptic inline tag.
function EvRow({ candidate, isRecommended }: { candidate: ActionEV; isRecommended: boolean }) {
  const probPct = Math.round(candidate.probability * 100);
  const negative = candidate.expected_value < 0;
  const barColor = probabilityTierColor(probPct);
  return (
    <tr className={isRecommended ? "border-l-2 border-accent bg-accent-soft/70" : "border-b border-border/50 last:border-0"}>
      <td className="px-2 py-2">
        <div className="flex items-center gap-1.5">
          <ActionBadge action={candidate.action_type} />
          {isRecommended && <span className="text-[10px] font-semibold text-accent-text">★ recommended</span>}
        </div>
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center justify-end gap-1.5">
          <div className="hidden h-1.5 w-10 overflow-hidden rounded-full bg-surface-2 sm:block">
            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${probPct}%` }} />
          </div>
          <span className={`font-mono-tabular ${isRecommended ? "font-semibold text-text" : "text-text-muted"}`}>
            {formatPercent(candidate.probability)}
          </span>
        </div>
      </td>
      <td className={`px-2 py-2 text-right font-mono-tabular ${isRecommended ? "text-text" : "text-text-muted"}`}>{formatCurrency(candidate.cost)}</td>
      <td className={`px-2 py-2 text-right font-mono-tabular ${isRecommended ? "text-text" : "text-text-muted"}`}>{formatCurrency(candidate.friction)}</td>
      <td className={`px-2 py-2 text-right font-mono-tabular font-semibold ${negative ? "text-status-danger" : "text-status-success"}`}>
        {formatCurrency(candidate.expected_value)}
      </td>
    </tr>
  );
}

function PolicyChecklist({ trace, policyResult }: { trace: DecisionTrace; policyResult: DecisionTrace["policy_checks"]["policy_result"] }) {
  const items: { label: string; pass: boolean | null; detail: string }[] = [
    {
      label: "Already-paid check",
      pass: !trace.policy_checks.is_actually_paid,
      detail: "Cross-referenced against the real payments ledger, not invoice status.",
    },
    {
      label: "Dispute check",
      pass: !trace.policy_checks.is_disputed,
      detail: trace.policy_checks.is_disputed ? "Disputed — ESCALATE/VOICE excluded from candidates." : "No dispute detected.",
    },
    {
      label: "Policy verdict",
      pass: policyResult ? policyResult === "allowed" : null,
      detail: policyResult ? `Result: ${policyResult}.` : "No policy verdict recorded for this round.",
    },
  ];

  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-start gap-2.5 text-sm">
          {item.pass === null ? (
            <MinusCircle size={16} className="mt-0.5 shrink-0 text-text-faint" />
          ) : item.pass ? (
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-status-success" />
          ) : (
            <XCircle size={16} className="mt-0.5 shrink-0 text-status-escalate" />
          )}
          <div>
            <span className="font-medium text-text">{item.label}</span>
            <span className="ml-1.5 text-text-faint">— {item.detail}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SafetyList({
  trace,
  policyResult,
  selectedAction,
}: {
  trace: DecisionTrace;
  policyResult: DecisionTrace["policy_checks"]["policy_result"];
  selectedAction: DecisionTrace["policy_checks"]["selected_action"];
}) {
  const items: ReactNode[] = [];

  if (trace.policy_checks.is_disputed) {
    items.push(<Item key="dispute" tone="dispute">Dispute detected — collections pressure withheld pending resolution.</Item>);
  }
  if (trace.policy_checks.is_actually_paid) {
    items.push(<Item key="paid" tone="success">Already paid — ledger not yet reconciled with invoice status.</Item>);
  }
  if (policyResult === "blocked") {
    items.push(<Item key="blocked" tone="danger">Policy blocked the proposed action.</Item>);
  } else if (policyResult === "escalated") {
    items.push(<Item key="escalated" tone="escalate">Routed to human approval (large-amount escalation threshold).</Item>);
  }

  const toolResult = trace.policy_checks.tool_result;
  const retryCount = trace.policy_checks.retry_count;
  if (toolResult) {
    if (!toolResult.success) {
      // Primary line is always a clean, generic sentence -- toolResult.message
      // is a raw string from whatever failed (e.g. a real Razorpay API error),
      // which can read as an alarming debug dump if it's the headline. Kept
      // visible for transparency, just de-emphasized below instead.
      items.push(
        <Item key="tool-failed" tone="danger">
          <div>
            Tool call failed ({toolResult.action})
            {typeof retryCount === "number" && (
              <> — retried {retryCount} time(s), then safely fell back to <strong>{selectedAction ?? "wait"}</strong>.</>
            )}
          </div>
          {toolResult.message && <div className="mt-1 text-[11px] text-text-faint">{toolResult.message}</div>}
        </Item>
      );
    } else if (typeof retryCount === "number" && retryCount > 0) {
      items.push(
        <Item key="tool-retried" tone="escalate">
          Tool call ({toolResult.action}) succeeded after {retryCount} retry attempt(s): {toolResult.message}
        </Item>
      );
    } else {
      items.push(
        <Item key="tool-ok" tone="success">
          Tool dispatched successfully ({toolResult.action}): {toolResult.message}
        </Item>
      );
    }
  } else if (trace.policy_checks.error) {
    items.push(<Item key="error" tone="danger">{trace.policy_checks.error}</Item>);
  }

  if (items.length === 0) {
    items.push(<Item key="none" tone="neutral">No safety interventions or failures this round — proceeded normally.</Item>);
  }

  return <ul className="space-y-2">{items}</ul>;
}

function Item({ tone, children }: { tone: "dispute" | "success" | "danger" | "escalate" | "neutral"; children: ReactNode }) {
  const dotClass = {
    dispute: "bg-status-dispute",
    success: "bg-status-success",
    danger: "bg-status-danger",
    escalate: "bg-status-escalate",
    neutral: "bg-text-faint",
  }[tone];
  return (
    <li className="flex items-start gap-2.5 text-sm text-text">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
      <span>{children}</span>
    </li>
  );
}

function LlmExtraction({ trace }: { trace: DecisionTrace }) {
  const eventType = trace.evidence.trigger_event?.event_type;

  if (eventType === "promise.created") {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-text">
          This round&rsquo;s customer response was processed by the promise-extraction LLM (
          <Badge tone="wait">Groq · openai/gpt-oss-120b</Badge> JSON mode, temperature 0 — the only LLM call in this
          system, and it never chooses an action).
        </p>
        <p className="flex items-center gap-2 text-text-muted">
          <Scale size={14} className="text-accent-text" />
          Result: a payment promise was extracted
          {trace.model_scores.ptp_probability !== null && (
            <> and scored at <strong className="text-text">{formatPercent(trace.model_scores.ptp_probability)}</strong> likelihood of being kept.</>
          )}
        </p>
      </div>
    );
  }
  if (eventType === "customer.responded") {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-text">
          This round processed a customer response through the promise-extraction LLM (
          <Badge tone="wait">Groq · openai/gpt-oss-120b</Badge> JSON mode, temperature 0).
        </p>
        <p className="text-text-muted">
          Result: no promise was extracted from this response. Either the message contained no specific commitment,
          or extraction failed twice and fell back — both outcomes are deliberately treated identically downstream.
        </p>
      </div>
    );
  }
  return <p className="text-sm text-text-muted">No LLM call was made for this round — the triggering event wasn&rsquo;t a customer response.</p>;
}
