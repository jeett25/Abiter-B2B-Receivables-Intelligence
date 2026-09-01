import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { ApiError, getDecision, getInvoice, getTimeline } from "@/lib/api";
import { ActionEV, DecisionTrace, InvoiceSummary, InvoiceTimeline } from "@/lib/types";
import RefreshButton from "../../RefreshButton";

// Screen 2 (master doc Day 3): click an invoice -> see the decision trace
// (root cause -> recoverability score -> candidate-action EV comparison ->
// policy check -> chosen action) in plain language. Day 6: connected to the
// real GET /api/invoices/{id}, /decision, /timeline endpoints.

// TimelineEntry.detail is Record<string, unknown> on the wire (raw JSONB,
// see lib/types.ts) -- state_transition_path is only ever populated for the
// Day-4 agent shape, so this validates rather than assumes the shape.
function getStateTransitionPath(detail: Record<string, unknown>): string[] | null {
  const path = detail.state_transition_path;
  if (!Array.isArray(path) || path.length === 0) return null;
  if (!path.every((s) => typeof s === "string")) return null;
  return path as string[];
}

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
        <p>
          <Link href="/invoices">&larr; Back to invoices</Link>
        </p>
        <p role="alert" style={{ color: "#b00020" }}>
          Failed to load invoice {invoiceId}: {message}
        </p>
        <Link href={`/invoices/${invoiceId}`}>Retry</Link>
      </div>
    );
  }

  const candidateActions = trace.model_scores.candidate_actions ?? [];
  const retrievedCases = trace.evidence.retrieved_cases ?? [];
  const sortedCandidates = [...candidateActions].sort(
    (a, b) => b.expected_value - a.expected_value
  );
  // selected_action (Day-4 agent shape) is what virtually every real row
  // carries; final_action (Day-3 legacy shape) is the fallback for the one
  // invoice still written by the older path. See lib/types.ts.
  const selectedAction = trace.policy_checks.selected_action ?? trace.policy_checks.final_action;
  const policyResult = trace.policy_checks.policy_result ?? trace.policy_checks.result;

  return (
    <div>
      <p>
        <Link href="/invoices">&larr; Back to invoices</Link>
      </p>
      <h1>
        {trace.invoice_number} -- {trace.customer_name}
        {" "}
        <RefreshButton />
      </h1>
      <p>
        Amount: Rs.{trace.amount.toLocaleString("en-IN")} &middot; Status: <strong>{invoice.current_state}</strong>{" "}
        &middot; Due {invoice.due_date}
        {invoice.treatment_group && (
          <>
            {" "}
            &middot; Attribution arm: <strong>{invoice.treatment_group}</strong>
          </>
        )}
      </p>
      <p style={{ fontSize: "0.85em" }}>
        Jump to: <a href="#policy-check">Policy check</a> &middot; <a href="#safety">Safety &amp; failure handling</a>
        {" "}
        &middot; <a href="#llm-extraction">LLM extraction</a> &middot; <a href="#timeline">Timeline</a>
      </p>

      <div style={{ border: "1px solid #888", padding: "0.75em 1em", marginBottom: "1em" }}>
        <strong>Why this decision?</strong>
        <p style={{ margin: "0.5em 0 0" }}>
          The system chose <strong>{trace.decision}</strong>. {trace.reason}
        </p>
        <p style={{ margin: "0.5em 0 0", fontSize: "0.85em", color: "#888" }}>
          This choice is fully deterministic -- the Economics Engine (candidate-action EV comparison, section 3)
          and the Policy/Safety Gate (section 5) make it, with no LLM involved. The only LLM in this system
          extracts payment promises from customer messages (section 8, when applicable) -- it never chooses an
          action.
        </p>
      </div>

      <h2>1. Root cause</h2>
      <p>{trace.policy_checks.is_disputed ? "Disputed -- collections pressure withheld pending resolution." : "No dispute detected."}</p>
      <p>{trace.policy_checks.is_actually_paid ? "Already paid -- ledger not yet reconciled with invoice status." : "Not yet paid."}</p>

      <h2>2. Recoverability score</h2>
      <p>
        {trace.model_scores.recovery_probability === null
          ? "No recovery-model score for this round (e.g. a promise-creation-only round)."
          : `${(trace.model_scores.recovery_probability * 100).toFixed(1)}% estimated probability of recovery (calibrated recovery model, no action applied).`}
      </p>

      <h2>3. Candidate-action comparison</h2>
      {sortedCandidates.length === 0 ? (
        <p>No candidate-action comparison for this round.</p>
      ) : (
        <table border={1} cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th>Action</th>
              <th>P(recovery)</th>
              <th>Cost</th>
              <th>Friction</th>
              <th>Expected Value</th>
            </tr>
          </thead>
          <tbody>
            {sortedCandidates.map((candidate: ActionEV) => (
              <tr
                key={candidate.action_type}
                style={
                  candidate.action_type === trace.policy_checks.proposed_action
                    ? { fontWeight: "bold" }
                    : undefined
                }
              >
                <td>
                  {candidate.action_type}
                  {candidate.action_type === trace.policy_checks.proposed_action ? " (proposed)" : ""}
                </td>
                <td>{(candidate.probability * 100).toFixed(1)}%</td>
                <td>Rs.{candidate.cost.toFixed(0)}</td>
                <td>Rs.{candidate.friction.toFixed(0)}</td>
                <td>Rs.{candidate.expected_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>4. Similar past cases</h2>
      {retrievedCases.length === 0 ? (
        <p>No comparable cases retrieved.</p>
      ) : (
        <ul>
          {retrievedCases.map((c) => (
            <li key={c.invoice_id}>{c.case_text}</li>
          ))}
        </ul>
      )}

      <h2 id="policy-check">5. Policy check</h2>
      <p>
        Result: <strong>{policyResult ?? "n/a"}</strong> -- {trace.reason}
      </p>
      {trace.policy_checks.proposed_action && selectedAction && trace.policy_checks.proposed_action !== selectedAction && (
        <p>
          Proposed <strong>{trace.policy_checks.proposed_action}</strong>,{" "}
          {policyResult === "allowed" ? (
            // "allowed" means the Policy Gate did NOT override anything --
            // a mismatch here can only come from dispatch_action's
            // tool-failure fallback (see section 6), a distinct mechanism
            // this text must not misattribute to policy.
            <>
              fell back to <strong>{selectedAction}</strong> after a tool failure -- see section 6.
            </>
          ) : (
            <>
              overridden to <strong>{selectedAction}</strong> by policy.
            </>
          )}
        </p>
      )}

      <h2 id="safety">6. Safety &amp; failure handling</h2>
      {(() => {
        const items: ReactNode[] = [];

        if (trace.policy_checks.is_disputed) {
          items.push(<li key="dispute">Dispute detected -- collections pressure withheld pending resolution.</li>);
        }
        if (trace.policy_checks.is_actually_paid) {
          items.push(<li key="paid">Already paid -- ledger not yet reconciled with invoice status.</li>);
        }
        if (policyResult === "blocked") {
          items.push(<li key="blocked">Policy blocked the proposed action.</li>);
        } else if (policyResult === "escalated") {
          items.push(<li key="escalated">Routed to human approval (large-amount escalation threshold).</li>);
        }

        const toolResult = trace.policy_checks.tool_result;
        const retryCount = trace.policy_checks.retry_count;
        if (toolResult) {
          if (!toolResult.success) {
            items.push(
              <li key="tool-failed">
                Tool call failed ({toolResult.action}): {toolResult.message}
                {typeof retryCount === "number" && (
                  <>
                    {" "}
                    -- retried {retryCount} time(s), then fell back to <strong>{selectedAction ?? "wait"}</strong>.
                  </>
                )}
              </li>
            );
          } else if (typeof retryCount === "number" && retryCount > 0) {
            items.push(
              <li key="tool-retried">
                Tool call ({toolResult.action}) succeeded after {retryCount} retry attempt(s): {toolResult.message}
              </li>
            );
          } else {
            items.push(
              <li key="tool-ok">
                Tool dispatched successfully ({toolResult.action}): {toolResult.message}
              </li>
            );
          }
        } else if (trace.policy_checks.error) {
          items.push(<li key="error">{trace.policy_checks.error}</li>);
        }

        if (items.length === 0) {
          items.push(<li key="none">No safety interventions or failures this round -- proceeded normally.</li>);
        }

        return <ul>{items}</ul>;
      })()}

      <h2>7. Chosen action</h2>
      <p style={{ fontSize: "1.2em" }}>
        <strong>{trace.decision}</strong>
      </p>

      <h2 id="llm-extraction">8. LLM: Promise extraction</h2>
      {(() => {
        const eventType = trace.evidence.trigger_event?.event_type;
        // "promise.created" is ONLY ever synthesized by the LLM extraction
        // step on success (confirmed against app/agent/nodes.py -- it's
        // constructed nowhere else in the codebase), so it replaces the
        // original "customer.responded" event on the SAME round before the
        // audit write. "customer.responded" surviving to the persisted
        // record means the LLM ran and found nothing (or failed) -- see
        // lib/types.ts and this project's own promise_extraction.py.
        if (eventType === "promise.created") {
          return (
            <>
              <p>
                This round&rsquo;s customer response was processed by the promise-extraction LLM (Groq, model{" "}
                <code>openai/gpt-oss-120b</code>, JSON mode, temperature 0 -- the only LLM call in this system, and
                it never chooses an action; see the callout above).
              </p>
              <p>
                Result: a payment promise was extracted
                {trace.model_scores.ptp_probability !== null && (
                  <>
                    {" "}
                    and scored at <strong>{(trace.model_scores.ptp_probability * 100).toFixed(1)}%</strong>{" "}
                    likelihood of being kept (Promise-to-Pay model)
                  </>
                )}
                .
              </p>
            </>
          );
        }
        if (eventType === "customer.responded") {
          return (
            <>
              <p>
                This round processed a customer response through the promise-extraction LLM (Groq, model{" "}
                <code>openai/gpt-oss-120b</code>, JSON mode, temperature 0 -- the only LLM call in this system, and
                it never chooses an action; see the callout above).
              </p>
              <p>
                Result: no promise was extracted from this response. Either the message contained no specific
                commitment, or extraction failed twice and fell back -- both outcomes are deliberately treated
                identically downstream, so which one happened isn&rsquo;t distinguishable from the persisted record
                (a documented design choice, not a gap in this dashboard).
              </p>
            </>
          );
        }
        return <p>No LLM call was made for this round -- the triggering event wasn&rsquo;t a customer response.</p>;
      })()}

      <h2 id="timeline">9. Timeline</h2>
      {timeline.events.length === 0 ? (
        <p>No recorded events for this invoice yet.</p>
      ) : (
        <ul>
          {timeline.events.map((event, i) => {
            const path = getStateTransitionPath(event.detail);
            return (
              <li key={i}>
                <strong>{new Date(event.timestamp).toLocaleString("en-IN")}</strong> [{event.type}] -- {event.summary}
                {path && (
                  <div style={{ fontSize: "0.85em", color: "#888" }}>Path: {path.join(" → ")}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
