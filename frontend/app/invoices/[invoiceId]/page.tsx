import Link from "next/link";
import { notFound } from "next/navigation";
import { mockDecisionTraces } from "@/lib/mockData";
import { ActionEV } from "@/lib/types";

// Screen 2 (master doc Day 3): click an invoice -> see the decision trace
// (root cause -> recoverability score -> candidate-action EV comparison ->
// policy check -> chosen action) in plain language. Data source is
// mockDecisionTraces for now -- Day 6 swaps this for a real
// GET /decisions/{invoiceId} call returning the same DecisionTrace shape
// (which mirrors decision_logs directly, see lib/types.ts).
export default async function DecisionTracePage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = await params;
  const trace = mockDecisionTraces[invoiceId];

  if (!trace) {
    notFound();
  }

  const sortedCandidates = [...trace.model_scores.candidate_actions].sort(
    (a, b) => b.expected_value - a.expected_value
  );

  return (
    <div>
      <p>
        <Link href="/invoices">&larr; Back to invoices</Link>
      </p>
      <h1>
        {trace.invoice_number} -- {trace.customer_name}
      </h1>
      <p>Amount: Rs.{trace.amount.toLocaleString("en-IN")}</p>

      <h2>1. Root cause</h2>
      <p>{trace.policy_checks.is_disputed ? "Disputed -- collections pressure withheld pending resolution." : "No dispute detected."}</p>
      <p>{trace.policy_checks.is_actually_paid ? "Already paid -- ledger not yet reconciled with invoice status." : "Not yet paid."}</p>

      <h2>2. Recoverability score</h2>
      <p>{(trace.model_scores.recovery_probability * 100).toFixed(1)}% estimated probability of recovery (calibrated recovery model, no action applied).</p>

      <h2>3. Candidate-action comparison</h2>
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

      <h2>4. Similar past cases</h2>
      {trace.evidence.retrieved_cases.length === 0 ? (
        <p>No comparable cases retrieved.</p>
      ) : (
        <ul>
          {trace.evidence.retrieved_cases.map((c) => (
            <li key={c.invoice_id}>{c.case_text}</li>
          ))}
        </ul>
      )}

      <h2>5. Policy check</h2>
      <p>
        Result: <strong>{trace.policy_checks.result}</strong> -- {trace.reason}
      </p>
      {trace.policy_checks.proposed_action !== trace.policy_checks.final_action && (
        <p>
          Proposed <strong>{trace.policy_checks.proposed_action}</strong>, overridden to{" "}
          <strong>{trace.policy_checks.final_action}</strong> by policy.
        </p>
      )}

      <h2>6. Chosen action</h2>
      <p style={{ fontSize: "1.2em" }}>
        <strong>{trace.decision}</strong>
      </p>
    </div>
  );
}
