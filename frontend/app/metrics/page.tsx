import { ApiError, getAttribution, getMetrics } from "@/lib/api";
import { AttributionResponse, MetricsResponse } from "@/lib/types";
import { ErrorPanel, PageHeader, StatTile, formatCurrency, formatPercent } from "@/lib/ui";
import RefreshButton from "../RefreshButton";
import ComparisonChart from "./ComparisonChart";
import SliceTable from "./SliceTable";

// Screen 3 (master doc Day 3): the baseline-vs-engine comparison, plus Day
// 5's randomized-holdout attribution experiment. Day 6: connected to the
// real GET /api/metrics and GET /api/attribution.

export default async function MetricsPage() {
  let metrics: MetricsResponse, attribution: AttributionResponse;
  try {
    [metrics, attribution] = await Promise.all([getMetrics(), getAttribution()]);
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "Unexpected error loading metrics.";
    return (
      <div>
        <PageHeader title="Baseline vs. Decision Engine" />
        <ErrorPanel message={`Failed to load metrics: ${message}`} retryHref="/metrics" />
      </div>
    );
  }

  const b = metrics.baseline;
  const e = metrics.engine;
  const netImprovement = e.net_expected_recovered - b.net_expected_recovered;

  const byAction = attribution.slices.filter((s) => s.segment === null && s.action !== null);
  const bySegment = attribution.slices.filter((s) => s.segment !== null && s.action === null);
  const pooled = attribution.slices.find((s) => s.segment === null && s.action === null);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Baseline vs. Decision Engine"
        subtitle={
          <>
            Expected-value comparison over the full {e.n_invoices}-invoice live pool. Both strategies use the same
            calibrated recovery-model probabilities — only the action choice differs, isolating the value the
            decision-intelligence layer contributes.{" "}
            <a href="#experiment" className="text-accent-text hover:underline">
              Jump to the attribution experiment ↓
            </a>
          </>
        }
        actions={<RefreshButton />}
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile label="Net improvement" value={formatCurrency(netImprovement)} tone="success" />
        <StatTile label="Unnecessary interventions avoided" value={String(metrics.unnecessary_interventions_avoided)} tone="accent" />
        <StatTile label="Engine recovery rate" value={formatPercent(e.recovery_rate)} />
        <StatTile label="Baseline recovery rate" value={formatPercent(b.recovery_rate)} />
      </div>

      <ComparisonChart baseline={b} engine={e} />

      <div className="overflow-hidden rounded-2xl border border-border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2/60 text-left text-xs font-medium uppercase tracking-wide text-text-muted">
              <th className="px-4 py-3">Metric</th>
              <th className="px-4 py-3">{b.strategy_name}</th>
              <th className="px-4 py-3">{e.strategy_name}</th>
            </tr>
          </thead>
          <tbody className="font-mono-tabular">
            <MetricRow label="Interventions / Wait / Stop" baseline={`${b.n_interventions} / ${b.n_wait} / ${b.n_stop}`} engine={`${e.n_interventions} / ${e.n_wait} / ${e.n_stop}`} />
            <MetricRow label="Gross expected recovered" baseline={formatCurrency(b.gross_expected_recovered)} engine={formatCurrency(e.gross_expected_recovered)} />
            <MetricRow label="Total cost + friction" baseline={formatCurrency(b.total_cost + b.total_friction)} engine={formatCurrency(e.total_cost + e.total_friction)} />
            <MetricRow label="Net expected recovered" baseline={formatCurrency(b.net_expected_recovered)} engine={formatCurrency(e.net_expected_recovered)} />
            <MetricRow label="Recovery rate" baseline={formatPercent(b.recovery_rate)} engine={formatPercent(e.recovery_rate)} />
          </tbody>
        </table>
      </div>

      <section id="experiment" className="scroll-mt-24 space-y-4">
        <PageHeader title={`Attribution experiment (${attribution.experiment_id})`} />
        {metrics.attribution === null ? (
          <p className="text-sm text-text-muted">Attribution experiment results are not available yet.</p>
        ) : (
          <>
            <p className="text-sm text-text-muted">
              Randomized holdout, pooled across the whole eligible population:{" "}
              <span className="font-mono-tabular text-text">{metrics.attribution.treatment_n}</span> treated vs.{" "}
              <span className="font-mono-tabular text-text">{metrics.attribution.control_n}</span> control invoices.
            </p>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <StatTile label="Treatment recovery" value={formatPercent(metrics.attribution.treatment_recovery_rate)} />
              <StatTile label="Control recovery" value={formatPercent(metrics.attribution.control_recovery_rate)} />
              <StatTile label="Incremental recovery" value={formatPercent(metrics.attribution.incremental_recovery_rate)} tone="success" />
              <StatTile label="Incremental recovered" value={formatCurrency(metrics.attribution.incremental_recovered_amount)} tone="success" />
              <StatTile label="Incremental net recovery" value={formatCurrency(metrics.attribution.incremental_net_recovery)} tone="accent" />
            </div>
            {pooled && pooled.recovery_rate_diff_z !== null && (
              <p className="text-xs text-text-faint">Signal strength (z): {pooled.recovery_rate_diff_z.toFixed(2)}</p>
            )}
          </>
        )}
      </section>

      <SliceTable title="By action" dimensionLabel="Action" rows={byAction} />
      <SliceTable title="By segment" dimensionLabel="Segment" rows={bySegment} />
    </div>
  );
}

function MetricRow({ label, baseline, engine }: { label: string; baseline: string; engine: string }) {
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="px-4 py-3 font-sans text-text-muted">{label}</td>
      <td className="px-4 py-3 text-text">{baseline}</td>
      <td className="px-4 py-3 text-status-success">{engine}</td>
    </tr>
  );
}
