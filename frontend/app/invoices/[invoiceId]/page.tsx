import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { ApiError, getDecision, getInvoice, getTimeline } from "@/lib/api";
import { ActionEV, DecisionTrace, InvoiceSummary, InvoiceTimeline } from "@/lib/types";
import {
  ActionBadge,
  Badge,
  Card,
  ErrorPanel,
  PageHeader,
  PolicyBadge,
  StateBadge,
  formatCurrency,
  formatPercent,
} from "@/lib/ui";
import RefreshButton from "../../RefreshButton";

// Screen 2 (master doc Day 3): click an invoice -> see the decision trace
// (root cause -> recoverability score -> candidate-action EV comparison ->
// policy check -> chosen action) in plain language. Day 6: connected to the
// real GET /api/invoices/{id}, /decision, /timeline endpoints.

function getStateTransitionPath(detail: Record<string, unknown>): string[] | null {
  const path = detail.state_transition_path;
  if (!Array.isArray(path) || path.length === 0) return null;
  if (!path.every((s) => typeof s === "string")) return null;
  return path as string[];
}

const JUMP_LINKS = [
  { href: "#policy-check", label: "Policy check" },
  { href: "#safety", label: "Safety & failure handling" },
  { href: "#llm-extraction", label: "LLM extraction" },
  { href: "#timeline", label: "Timeline" },
];

export default async function DecisionTracePage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = await params;

  let invoice: InvoiceSummary, trace: DecisionTrace, timeline: InvoiceTimeline;
  try {
    [invoice, trace, timeline] = await Promise.all([
      getInvoice(invoiceId),
      getDecision(invoiceId),
      getTimeline(invoiceId),
    ]);
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
  const maxEv = Math.max(1, ...sortedCandidates.map((c) => Math.abs(c.expected_value)));
  const selectedAction = trace.policy_checks.selected_action ?? trace.policy_checks.final_action;
  const policyResult = trace.policy_checks.policy_result ?? trace.policy_checks.result;

  return (
    <div className="space-y-6">
      <BackLink />

      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            <span className="font-mono-tabular">{trace.invoice_number}</span>
            <span className="text-text-faint">·</span>
            {trace.customer_name}
          </span>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono-tabular text-text">{formatCurrency(trace.amount)}</span>
            <span>·</span>
            <StateBadge state={invoice.current_state} />
            <span>· Due {invoice.due_date}</span>
            {invoice.treatment_group && (
              <>
                <span>·</span>
                <Badge tone="neutral">Attribution: {invoice.treatment_group}</Badge>
              </>
            )}
          </span>
        }
        actions={<RefreshButton />}
      />

      <nav className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-muted">
        {JUMP_LINKS.map((l) => (
          <a key={l.href} href={l.href} className="hover:text-accent-text transition-colors">
            {l.label}
          </a>
        ))}
      </nav>

      <Card className="border-accent/25 bg-accent-soft/40 p-5 sm:p-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-accent-text">Why this decision?</div>
        <p className="mt-2 text-lg font-medium text-text">
          The system chose <span className="text-accent-text">{trace.decision}</span>.
        </p>
        <p className="mt-1 text-sm text-text-muted">{trace.reason}</p>
        <p className="mt-3 text-xs text-text-faint">
          This choice is fully deterministic — the Economics Engine (candidate-action EV comparison, section 3) and
          the Policy/Safety Gate (section 5) make it, with no LLM involved. The only LLM in this system extracts
          payment promises from customer messages (section 8, when applicable) — it never chooses an action.
        </p>
      </Card>

      <SectionCard index={1} title="Root cause">
        <ul className="space-y-1.5 text-sm text-text">
          <li className="flex items-center gap-2">
            <Dot ok={!trace.policy_checks.is_disputed} />
            {trace.policy_checks.is_disputed
              ? "Disputed — collections pressure withheld pending resolution."
              : "No dispute detected."}
          </li>
          <li className="flex items-center gap-2">
            <Dot ok={!trace.policy_checks.is_actually_paid} />
            {trace.policy_checks.is_actually_paid
              ? "Already paid — ledger not yet reconciled with invoice status."
              : "Not yet paid."}
          </li>
        </ul>
      </SectionCard>

      <SectionCard index={2} title="Recoverability score">
        {trace.model_scores.recovery_probability === null ? (
          <p className="text-sm text-text-muted">No recovery-model score for this round (e.g. a promise-creation-only round).</p>
        ) : (
          <div className="flex items-center gap-4">
            <div className="text-3xl font-semibold font-mono-tabular text-text">
              {formatPercent(trace.model_scores.recovery_probability)}
            </div>
            <div className="flex-1">
              <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${trace.model_scores.recovery_probability * 100}%` }}
                />
              </div>
              <p className="mt-1.5 text-xs text-text-faint">
                Calibrated recovery-model probability, no action applied.
              </p>
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard index={3} title="Candidate-action comparison">
        {sortedCandidates.length === 0 ? (
          <p className="text-sm text-text-muted">No candidate-action comparison for this round.</p>
        ) : (
          <div className="space-y-2">
            {sortedCandidates.map((candidate: ActionEV) => (
              <EvRow
                key={candidate.action_type}
                candidate={candidate}
                maxEv={maxEv}
                isProposed={candidate.action_type === trace.policy_checks.proposed_action}
              />
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard index={4} title="Similar past cases">
        {retrievedCases.length === 0 ? (
          <p className="text-sm text-text-muted">No comparable cases retrieved.</p>
        ) : (
          <ul className="space-y-2">
            {retrievedCases.map((c) => (
              <li key={c.invoice_id} className="rounded-lg border border-border bg-surface-2/50 p-3 text-sm text-text-muted">
                {c.case_text}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard id="policy-check" index={5} title="Policy check">
        <div className="flex items-center gap-3">
          <span className="text-sm text-text-muted">Result:</span>
          <PolicyBadge result={policyResult} />
        </div>
        <p className="mt-2 text-sm text-text-muted">{trace.reason}</p>
        {trace.policy_checks.proposed_action && selectedAction && trace.policy_checks.proposed_action !== selectedAction && (
          <p className="mt-2 text-sm text-text">
            Proposed <ActionBadge action={trace.policy_checks.proposed_action} />
            {" "}
            {policyResult === "allowed" ? (
              <>
                fell back to <ActionBadge action={selectedAction} /> after a tool failure — see section 6.
              </>
            ) : (
              <>
                overridden to <ActionBadge action={selectedAction} /> by policy.
              </>
            )}
          </p>
        )}
      </SectionCard>

      <SectionCard id="safety" index={6} title="Safety & failure handling">
        <SafetyList trace={trace} policyResult={policyResult} selectedAction={selectedAction} />
      </SectionCard>

      <SectionCard index={7} title="Chosen action">
        <div className="flex items-center gap-3">
          <ActionBadge action={selectedAction ?? null} />
          <span className="font-mono-tabular text-lg font-semibold text-text">{trace.decision}</span>
        </div>
      </SectionCard>

      <SectionCard id="llm-extraction" index={8} title="LLM: Promise extraction">
        <LlmExtraction trace={trace} />
      </SectionCard>

      <SectionCard id="timeline" index={9} title="Timeline">
        {timeline.events.length === 0 ? (
          <p className="text-sm text-text-muted">No recorded events for this invoice yet.</p>
        ) : (
          <ol className="relative space-y-5 border-l border-border pl-5">
            {timeline.events.map((event, i) => {
              const path = getStateTransitionPath(event.detail);
              return (
                <li key={i} className="relative">
                  <span className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full bg-accent ring-4 ring-bg" />
                  <div className="text-xs font-mono-tabular text-text-faint">
                    {new Date(event.timestamp).toLocaleString("en-IN")}
                  </div>
                  <div className="mt-0.5 text-sm text-text">
                    <span className="mr-1.5 inline-block rounded bg-surface-2 px-1.5 py-0.5 text-xs uppercase tracking-wide text-text-muted">
                      {event.type}
                    </span>
                    {event.summary}
                  </div>
                  {path && (
                    <div className="mt-1 font-mono-tabular text-xs text-accent-text">{path.join(" → ")}</div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </SectionCard>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/invoices" className="inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-text transition-colors">
      ← Back to invoices
    </Link>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-status-success" : "bg-status-danger"}`} />;
}

function SectionCard({
  id,
  index,
  title,
  children,
}: {
  id?: string;
  index: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <Card className="p-5 sm:p-6">
        <h2 className="mb-4 flex items-center gap-2.5 text-sm font-semibold uppercase tracking-wide text-text-muted">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono-tabular text-[11px] normal-case text-accent-text">
            {index}
          </span>
          {title}
        </h2>
        {children}
      </Card>
    </section>
  );
}

function EvRow({ candidate, maxEv, isProposed }: { candidate: ActionEV; maxEv: number; isProposed: boolean }) {
  const pct = Math.max(4, (Math.abs(candidate.expected_value) / maxEv) * 100);
  const negative = candidate.expected_value < 0;
  return (
    <div className={`rounded-lg border p-3 ${isProposed ? "border-accent/40 bg-accent-soft/30" : "border-border bg-surface-2/40"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ActionBadge action={candidate.action_type} />
          {isProposed && <span className="text-xs font-medium text-accent-text">proposed</span>}
        </div>
        <div className="flex items-center gap-4 font-mono-tabular text-xs text-text-muted">
          <span>P {formatPercent(candidate.probability)}</span>
          <span>Cost {formatCurrency(candidate.cost)}</span>
          <span>Friction {formatCurrency(candidate.friction)}</span>
          <span className={`font-semibold ${negative ? "text-status-danger" : "text-status-success"}`}>
            EV {formatCurrency(candidate.expected_value)}
          </span>
        </div>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div
          className={`h-full rounded-full ${negative ? "bg-status-danger" : "bg-status-success"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
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
      items.push(
        <Item key="tool-failed" tone="danger">
          Tool call failed ({toolResult.action}): {toolResult.message}
          {typeof retryCount === "number" && (
            <> — retried {retryCount} time(s), then fell back to <strong>{selectedAction ?? "wait"}</strong>.</>
          )}
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
        <p className="text-text-muted">
          Result: a payment promise was extracted
          {trace.model_scores.ptp_probability !== null && (
            <> and scored at <strong className="text-text">{formatPercent(trace.model_scores.ptp_probability)}</strong> likelihood of being kept (Promise-to-Pay model).</>
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
