import { Layers, ShieldCheck, Target, TrendingUp } from "lucide-react";
import { ApiError, getAttribution, getMetrics } from "@/lib/api";
import { ActionType, AttributionResponse, MetricsResponse } from "@/lib/types";
import { Card, ErrorPanel, IconStat, PageHeader, actionMeta, formatCurrency, formatPercent, signTone } from "@/lib/ui";
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
  const pooledSlice = attribution.slices.find((s) => s.segment === null && s.action === null);

  const actionLiftData = byAction.map((r) => ({
    label: actionMeta(r.action as ActionType).label,
    value: r.incremental_net_recovery,
    n: Math.min(r.treatment_n, r.control_n),
  }));
  const segmentLiftData = bySegment.map((r) => ({
    label: r.segment as string,
    value: r.incremental_net_recovery,
    n: Math.min(r.treatment_n, r.control_n),
  }));

  // COUNT-based incremental (fraction of invoices recovered) -- the metric
  // recovery_rate_diff_z is actually computed on, distinct from the
  // amount-weighted incremental_recovery_rate above it. Null whenever
  // either arm lacks the field (e.g. before a fresh attribution run).
  const countIncremental =
    metrics.attribution?.treatment_count_recovery_rate != null && metrics.attribution?.control_count_recovery_rate != null
      ? metrics.attribution.treatment_count_recovery_rate - metrics.attribution.control_count_recovery_rate
      : null;
  const pooledZ = pooledSlice?.recovery_rate_diff_z ?? null;

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
        <h2 className="section-heading">Randomized holdout attribution</h2>
        {metrics.attribution === null ? (
          <Card className="p-6">
            <p className="text-sm text-text-muted">Attribution experiment results are not available yet.</p>
          </Card>
        ) : (
          <>
            <div className="space-y-5">
              <div>
                <div className="label mb-2.5 !text-text-faint">By recovered amount (weighted by invoice size)</div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <IconStat icon={Target} label="Treatment recovery" value={formatPercent(metrics.attribution.treatment_recovery_rate)} tone="neutral" />
                  <IconStat icon={Target} label="Control recovery" value={formatPercent(metrics.attribution.control_recovery_rate)} tone="neutral" />
                  <IconStat
                    icon={TrendingUp}
                    label="Incremental recovery"
                    value={formatPercent(metrics.attribution.incremental_recovery_rate)}
                    tone={signTone(metrics.attribution.incremental_recovery_rate)}
                    sub="no valid significance test at this sample size -- a handful of large invoices can swing this"
                  />
                </div>
              </div>
              <div>
                <div className="label mb-2.5 !text-text-faint">By invoice count (statistically tested)</div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <IconStat
                    icon={Target}
                    label="Treatment recovery"
                    value={metrics.attribution.treatment_count_recovery_rate != null ? formatPercent(metrics.attribution.treatment_count_recovery_rate) : "n/a"}
                    tone="neutral"
                  />
                  <IconStat
                    icon={Target}
                    label="Control recovery"
                    value={metrics.attribution.control_count_recovery_rate != null ? formatPercent(metrics.attribution.control_count_recovery_rate) : "n/a"}
                    tone="neutral"
                  />
                  <IconStat
                    icon={TrendingUp}
                    label="Incremental recovery"
                    value={countIncremental !== null ? formatPercent(countIncremental) : "n/a"}
                    tone={countIncremental !== null ? signTone(countIncremental) : "neutral"}
                    sub={
                      pooledZ !== null
                        ? `z = ${pooledZ.toFixed(2)} — ${Math.abs(pooledZ) >= 1.96 ? "significant at 95% confidence" : "not statistically significant yet"}`
                        : undefined
                    }
                  />
                </div>
              </div>
              <IconStat
                icon={TrendingUp}
                label="Incremental net recovery (₹)"
                value={formatCurrency(metrics.attribution.incremental_net_recovery)}
                tone={signTone(metrics.attribution.incremental_net_recovery)}
                sub="cost- and friction-adjusted"
              />
              {attribution.cuped && (
                <div className="rounded-card border border-dashed border-border-strong p-4">
                  <div className="label mb-2 !text-text-faint">Variance-reduced estimate (CUPED)</div>
                  {attribution.cuped
                    .filter((c) => c.metric === "count" && c.raw_se != null && c.cuped_se != null)
                    .map((c) => (
                      <p key={c.metric} className="text-sm text-text-muted">
                        Using the recovery model&apos;s pre-treatment probability as a covariate (r = {c.corr.toFixed(2)}),
                        the count-based incremental recovery estimate&apos;s standard error tightens from{" "}
                        <span className="text-text">±{((c.raw_se as number) * 100).toFixed(1)}pp</span> to{" "}
                        <span className="text-text">±{((c.cuped_se as number) * 100).toFixed(1)}pp</span>
                        {c.se_reduction_pct != null && <> ({c.se_reduction_pct.toFixed(0)}% smaller)</>} — the underlying
                        effect (+{(c.cuped_effect * 100).toFixed(1)}pp vs. raw +{(c.raw_effect * 100).toFixed(1)}pp) stays
                        close to the raw estimate, as it should: CUPED changes precision, not the answer, and is never
                        used to prefer one number over the other.
                      </p>
                    ))}
                </div>
              )}
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
