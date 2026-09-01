import Link from "next/link";
import { ApiError, getAttribution, getMetrics } from "@/lib/api";
import { AttributionResponse, AttributionSliceOut, EvaluationSummary, MetricsResponse } from "@/lib/types";
import RefreshButton from "../RefreshButton";

// Screen 3 (master doc Day 3): the baseline-vs-engine comparison, plus Day
// 5's randomized-holdout attribution experiment. Day 6: connected to the
// real GET /api/metrics and GET /api/attribution.
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

function SliceTable({ title, dimensionLabel, rows }: { title: string; dimensionLabel: string; rows: AttributionSliceOut[] }) {
  if (rows.length === 0) {
    return (
      <>
        <h2>{title}</h2>
        <p>No slices available.</p>
      </>
    );
  }
  return (
    <>
      <h2>{title}</h2>
      <table border={1} cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th>{dimensionLabel}</th>
            <th>Treatment n</th>
            <th>Control n</th>
            <th>Treatment recovery rate</th>
            <th>Control recovery rate</th>
            <th>Incremental recovery rate</th>
            <th>Incremental recovered</th>
            <th>Incremental net recovery</th>
            <th>z</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.segment ?? "all"}-${r.action ?? "all"}`}>
              <td>{r.segment ?? r.action ?? "(pooled)"}</td>
              <td>{r.treatment_n}</td>
              <td>{r.control_n}</td>
              <td>{(r.treatment_recovery_rate * 100).toFixed(1)}%</td>
              <td>{(r.control_recovery_rate * 100).toFixed(1)}%</td>
              <td>{(r.incremental_recovery_rate * 100).toFixed(1)}%</td>
              <td>{formatCurrency(r.incremental_recovered_amount)}</td>
              <td>{formatCurrency(r.incremental_net_recovery)}</td>
              <td>{r.recovery_rate_diff_z !== null ? r.recovery_rate_diff_z.toFixed(2) : "n/a"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export default async function MetricsPage() {
  let metrics: MetricsResponse, attribution: AttributionResponse;
  try {
    [metrics, attribution] = await Promise.all([getMetrics(), getAttribution()]);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Unexpected error loading metrics.";
    return (
      <div>
        <h1>Baseline vs. Decision Engine</h1>
        <p role="alert" style={{ color: "#b00020" }}>
          Failed to load metrics: {message}
        </p>
        <Link href="/metrics">Retry</Link>
      </div>
    );
  }

  const b: EvaluationSummary = metrics.baseline;
  const e: EvaluationSummary = metrics.engine;
  const netImprovement = e.net_expected_recovered - b.net_expected_recovered;

  const byAction = attribution.slices.filter((s) => s.segment === null && s.action !== null);
  const bySegment = attribution.slices.filter((s) => s.segment !== null && s.action === null);
  const pooled = attribution.slices.find((s) => s.segment === null && s.action === null);

  return (
    <div>
      <h1>
        Baseline vs. Decision Engine
        {" "}
        <RefreshButton />
      </h1>
      <p>
        Expected-value comparison over the full {e.n_invoices}-invoice live pool. Both strategies use the
        same calibrated recovery-model probabilities -- only the action choice differs, isolating the value
        the decision-intelligence layer contributes. <a href="#experiment">Jump to the attribution experiment.</a>
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
        <li>Unnecessary interventions avoided: {metrics.unnecessary_interventions_avoided}</li>
      </ul>

      <h1 id="experiment">Attribution experiment ({attribution.experiment_id})</h1>
      {metrics.attribution === null ? (
        <p>Attribution experiment results are not available yet.</p>
      ) : (
        <>
          <p>
            Randomized holdout, pooled across the whole eligible population: {metrics.attribution.treatment_n}{" "}
            treated vs. {metrics.attribution.control_n} control invoices.
          </p>
          <ul>
            <li>Treatment recovery rate: {(metrics.attribution.treatment_recovery_rate * 100).toFixed(1)}%</li>
            <li>Control recovery rate: {(metrics.attribution.control_recovery_rate * 100).toFixed(1)}%</li>
            <li>Incremental recovery rate: {(metrics.attribution.incremental_recovery_rate * 100).toFixed(1)}%</li>
            <li>Incremental recovered amount: {formatCurrency(metrics.attribution.incremental_recovered_amount)}</li>
            <li>Incremental net recovery: {formatCurrency(metrics.attribution.incremental_net_recovery)}</li>
            {pooled && pooled.recovery_rate_diff_z !== null && (
              <li>Signal strength (z): {pooled.recovery_rate_diff_z.toFixed(2)}</li>
            )}
          </ul>
        </>
      )}

      <SliceTable title="By action" dimensionLabel="Action" rows={byAction} />
      <SliceTable title="By segment" dimensionLabel="Segment" rows={bySegment} />
    </div>
  );
}
