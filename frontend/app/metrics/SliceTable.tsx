import { AttributionSliceOut } from "@/lib/types";
import { Card, EmptyState, formatCurrency, formatPercent } from "@/lib/ui";

export default function SliceTable({
  title,
  dimensionLabel,
  rows,
}: {
  title: string;
  dimensionLabel: string;
  rows: AttributionSliceOut[];
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-text-muted">{title}</h2>
      {rows.length === 0 ? (
        <EmptyState>No slices available.</EmptyState>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-2/60 text-left text-xs font-medium uppercase tracking-wide text-text-muted">
                  <th className="px-4 py-3">{dimensionLabel}</th>
                  <th className="px-4 py-3 text-right">Treatment n</th>
                  <th className="px-4 py-3 text-right">Control n</th>
                  <th className="px-4 py-3 text-right">Treatment rate</th>
                  <th className="px-4 py-3 text-right">Control rate</th>
                  <th className="px-4 py-3 text-right">Incremental rate</th>
                  <th className="px-4 py-3 text-right">Incremental recovered</th>
                  <th className="px-4 py-3 text-right">Incremental net</th>
                  <th className="px-4 py-3 text-right">z</th>
                </tr>
              </thead>
              <tbody className="font-mono-tabular">
                {rows.map((r) => {
                  const label = r.segment ?? r.action ?? "(pooled)";
                  const positive = r.incremental_net_recovery >= 0;
                  return (
                    <tr key={`${r.segment ?? "all"}-${r.action ?? "all"}`} className="border-b border-border/60 last:border-0 hover:bg-surface-hover transition-colors">
                      <td className="px-4 py-3 font-sans text-text">{label}</td>
                      <td className="px-4 py-3 text-right text-text-muted">{r.treatment_n}</td>
                      <td className="px-4 py-3 text-right text-text-muted">{r.control_n}</td>
                      <td className="px-4 py-3 text-right text-text-muted">{formatPercent(r.treatment_recovery_rate)}</td>
                      <td className="px-4 py-3 text-right text-text-muted">{formatPercent(r.control_recovery_rate)}</td>
                      <td className="px-4 py-3 text-right text-text">{formatPercent(r.incremental_recovery_rate)}</td>
                      <td className="px-4 py-3 text-right text-text">{formatCurrency(r.incremental_recovered_amount)}</td>
                      <td className={`px-4 py-3 text-right font-semibold ${positive ? "text-status-success" : "text-status-danger"}`}>
                        {formatCurrency(r.incremental_net_recovery)}
                      </td>
                      <td className="px-4 py-3 text-right text-text-faint">
                        {r.recovery_rate_diff_z !== null ? r.recovery_rate_diff_z.toFixed(2) : "n/a"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </section>
  );
}
