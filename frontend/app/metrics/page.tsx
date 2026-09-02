import { Layers, ShieldCheck, Target, TrendingUp } from "lucide-react";
import { ApiError, getAttribution, getMetrics } from "@/lib/api";
import { ActionType, AttributionResponse, MetricsResponse } from "@/lib/types";
import { Card, ErrorPanel, IconStat, PageHeader, actionMeta, formatCurrency, formatPercent } from "@/lib/ui";
import RefreshButton from "../RefreshButton";
import AttributionCompareChart from "./AttributionCompareChart";
import ComparisonChart from "./ComparisonChart";
import DecisionMixChart from "./DecisionMixChart";
import RecoveryGauges from "./RecoveryGauges";
import SliceLiftChart from "./SliceLiftChart";
import SliceTable from "./SliceTable";

// Screen 3 (master doc Day 3): the baseline-vs-engine comparison, plus Day
// 5's randomized-holdout attribution experiment. Day 6 Phase C redesign:
// every number on this page still traces back to GET /api/metrics and
// GET /api/attribution directly -- no chart here invents a data point that
// wasn't already in one of those two responses.

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
  const recoveryDeltaPts = (e.recovery_rate - b.recovery_rate) * 100;

  const byAction = attribution.slices.filter((s) => s.segment === null && s.action !== null);
  const bySegment = attribution.slices.filter((s) => s.segment !== null && s.action === null);

  const actionLiftData = byAction.map((r) => ({
    label: actionMeta(r.action as ActionType).label,
    value: r.incremental_net_recovery,
  }));
  const segmentLiftData = bySegment.map((r) => ({
    label: r.segment as string,
    value: r.incremental_net_recovery,
  }));

  return (
    <div className="space-y-10">
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
        <IconStat
          icon={TrendingUp}
          label="Net EV improvement"
          value={formatCurrency(netImprovement)}
          sub={`${e.strategy_name} vs. ${b.strategy_name}, full live pool`}
          tone="success"
        />
        <IconStat
          icon={Target}
          label="Engine recovery rate"
          value={formatPercent(e.recovery_rate)}
          sub={`${recoveryDeltaPts >= 0 ? "+" : ""}${recoveryDeltaPts.toFixed(1)} pts vs. baseline`}
          tone="accent"
        />
        <IconStat
          icon={ShieldCheck}
          label="Unnecessary interventions avoided"
          value={String(metrics.unnecessary_interventions_avoided)}
          sub="invoices the engine correctly left alone"
          tone="accent"
        />
        <IconStat
          icon={Layers}
          label="Invoices evaluated"
          value={String(e.n_invoices)}
          sub="live pool, both strategies scored identically"
          tone="neutral"
        />
      </div>

      <section className="space-y-4">
        <h2 className="section-heading">Engine vs. baseline economics</h2>
        <div className="grid gap-4 md:grid-cols-[0.85fr_1.6fr]">
          <RecoveryGauges baseline={b} engine={e} />
          <ComparisonChart baseline={b} engine={e} />
        </div>
        <DecisionMixChart baseline={b} engine={e} />
        <Card className="overflow-hidden p-0">
          <div className="label !text-text-muted border-b border-border px-5 py-3.5">Full comparison</div>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-2/60 text-left">
                <th className="label px-4 py-3 !text-[10px] !text-text-faint">Metric</th>
                <th className="label px-4 py-3 !text-[10px] !text-text-faint">{b.strategy_name}</th>
                <th className="label px-4 py-3 !text-[10px] !text-text-faint">{e.strategy_name}</th>
              </tr>
            </thead>
            <tbody className="font-mono-tabular">
              <MetricRow
                label="Interventions / Wait / Stop"
                baseline={`${b.n_interventions} / ${b.n_wait} / ${b.n_stop}`}
                engine={`${e.n_interventions} / ${e.n_wait} / ${e.n_stop}`}
              />
              <MetricRow label="Gross expected recovered" baseline={formatCurrency(b.gross_expected_recovered)} engine={formatCurrency(e.gross_expected_recovered)} />
              <MetricRow label="Total cost + friction" baseline={formatCurrency(b.total_cost + b.total_friction)} engine={formatCurrency(e.total_cost + e.total_friction)} />
              <MetricRow label="Net expected recovered" baseline={formatCurrency(b.net_expected_recovered)} engine={formatCurrency(e.net_expected_recovered)} />
              <MetricRow label="Recovery rate" baseline={formatPercent(b.recovery_rate)} engine={formatPercent(e.recovery_rate)} />
            </tbody>
          </table>
        </Card>
      </section>

      <section id="experiment" className="scroll-mt-24 space-y-4">
        <h2 className="section-heading">Randomized holdout attribution ({attribution.experiment_id})</h2>
        {metrics.attribution === null ? (
          <Card className="p-6">
            <p className="text-sm text-text-muted">Attribution experiment results are not available yet.</p>
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <IconStat icon={Target} label="Treatment recovery" value={formatPercent(metrics.attribution.treatment_recovery_rate)} tone="neutral" />
              <IconStat icon={Target} label="Control recovery" value={formatPercent(metrics.attribution.control_recovery_rate)} tone="neutral" />
              <IconStat icon={TrendingUp} label="Incremental recovery" value={formatPercent(metrics.attribution.incremental_recovery_rate)} tone="success" />
              <IconStat icon={TrendingUp} label="Incremental net recovery" value={formatCurrency(metrics.attribution.incremental_net_recovery)} tone="accent" />
            </div>
            <AttributionCompareChart headline={metrics.attribution} />
          </>
        )}
      </section>

      {metrics.attribution !== null && (
        <>
          <section className="space-y-4">
            <h2 className="section-heading">Incremental impact — by action</h2>
            <SliceLiftChart title="Incremental net recovery, by action" data={actionLiftData} />
            <SliceTable title="By action" dimensionLabel="Action" rows={byAction} />
          </section>

          <section className="space-y-4">
            <h2 className="section-heading">Incremental impact — by segment</h2>
            <SliceLiftChart title="Incremental net recovery, by segment" data={segmentLiftData} />
            <SliceTable title="By segment" dimensionLabel="Segment" rows={bySegment} />
          </section>
        </>
      )}
    </div>
  );
}

function MetricRow({ label, baseline, engine }: { label: string; baseline: string; engine: string }) {
  return (
    <tr className="border-b border-border/50 last:border-0">
      <td className="px-4 py-3 font-sans text-text-muted">{label}</td>
      <td className="px-4 py-3 text-text">{baseline}</td>
      <td className="px-4 py-3 text-status-success">{engine}</td>
    </tr>
  );
}
