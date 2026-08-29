import {
  mockBaselineSummary,
  mockEngineSummary,
  mockEscalationAppropriateness,
  mockUnnecessaryInterventionsAvoided,
} from "@/lib/mockData";
import { EvaluationSummary } from "@/lib/types";

// Screen 3 (master doc Day 3): the baseline-vs-engine comparison -- called
// out in the master doc as "your best slide". Numbers here are the real
// output of backend/app/decision/evaluation.py's full 900-invoice run (Day 3
// subtask 7), not fabricated -- Day 6 swaps the import for a live API call
// returning the same EvaluationSummary shape.
function formatCurrency(value: number): string {
  return `Rs.${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function SummaryRow({ label, baseline, engine }: { label: string; baseline: string; engine: string }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{baseline}</td>
      <td>{engine}</td>
    </tr>
  );
}

export default function MetricsPage() {
  const b: EvaluationSummary = mockBaselineSummary;
  const e: EvaluationSummary = mockEngineSummary;
  const netImprovement = e.net_expected_recovered - b.net_expected_recovered;

  return (
    <div>
      <h1>Baseline vs. Decision Engine</h1>
      <p>
        Expected-value comparison over the full {e.n_invoices}-invoice live pool. Both strategies use the
        same calibrated recovery-model probabilities -- only the action choice differs, isolating the value
        the decision-intelligence layer contributes. This is NOT a comparison against real observed
        outcomes (the live pool is unresolved); that comparison is Day 5's randomized-holdout Attribution
        Engine.
      </p>

      <table border={1} cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th>Metric</th>
            <th>{b.strategy_name}</th>
            <th>{e.strategy_name}</th>
          </tr>
        </thead>
        <tbody>
          <SummaryRow
            label="Interventions / Wait / Stop"
            baseline={`${b.n_interventions} / ${b.n_wait} / ${b.n_stop}`}
            engine={`${e.n_interventions} / ${e.n_wait} / ${e.n_stop}`}
          />
          <SummaryRow
            label="Gross expected recovered"
            baseline={formatCurrency(b.gross_expected_recovered)}
            engine={formatCurrency(e.gross_expected_recovered)}
          />
          <SummaryRow
            label="Total cost + friction"
            baseline={formatCurrency(b.total_cost + b.total_friction)}
            engine={formatCurrency(e.total_cost + e.total_friction)}
          />
          <SummaryRow
            label="Net expected recovered"
            baseline={formatCurrency(b.net_expected_recovered)}
            engine={formatCurrency(e.net_expected_recovered)}
          />
          <SummaryRow
            label="Recovery rate"
            baseline={`${(b.recovery_rate * 100).toFixed(1)}%`}
            engine={`${(e.recovery_rate * 100).toFixed(1)}%`}
          />
        </tbody>
      </table>

      <h2>Headline numbers</h2>
      <ul>
        <li>Net improvement (engine - baseline): {formatCurrency(netImprovement)}</li>
        <li>Unnecessary interventions avoided: {mockUnnecessaryInterventionsAvoided}</li>
      </ul>

      <h2>Escalation-appropriateness diagnostic</h2>
      <p>
        Of {mockEscalationAppropriateness.n_escalated} invoices escalated, {" "}
        {(mockEscalationAppropriateness.high_uplift_share * 100).toFixed(1)}% belong to the archetype with
        the highest true escalate-uplift (diagnostic only -- hidden ground truth, never a decision input),
        while {(mockEscalationAppropriateness.low_uplift_share * 100).toFixed(1)}% belong to archetypes with
        near-zero true escalate-uplift -- a known limitation of the current flat-uplift assumption, to be
        validated/corrected by Day 5's Attribution Engine.
      </p>
    </div>
  );
}
