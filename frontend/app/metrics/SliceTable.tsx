import { AttributionSliceOut } from "@/lib/types";
import { Card, EmptyState, actionMeta, formatCurrency, formatPercent } from "@/lib/ui";

const SIG_THRESHOLD = 1.96;
// Matches SliceLiftChart's threshold -- a row below this is too small a
// sample per arm to read its own rates/z with any confidence.
const LOW_N_THRESHOLD = 15;

export default function SliceTable({
  title,
  dimensionLabel,
  rows,
}: {
  title: string;
  dimensionLabel: string;
  rows: AttributionSliceOut[];
}) {
  if (rows.length === 0) {
    return <EmptyState>No {dimensionLabel.toLowerCase()} slices available.</EmptyState>;
  }

  const anyLowN = rows.some((r) => Math.min(r.treatment_n, r.control_n) < LOW_N_THRESHOLD);

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border px-5 py-3.5">
        <div className="label !text-text-muted">{title}</div>
        {anyLowN && (
          <p className="mt-1 text-xs text-text-faint">
            Faded rows have fewer than {LOW_N_THRESHOLD} invoices per arm — too small a sample to read confidently.
          </p>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-2/60 text-left">
              <th className="label px-4 py-3 !text-[10px] !text-text-faint">{dimensionLabel}</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Treatment n</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Control n</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Treatment rate</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Control rate</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Incremental rate</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Incremental recovered</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">Incremental net</th>
              <th className="label px-4 py-3 text-right !text-[10px] !text-text-faint">z</th>
            </tr>
          </thead>
          <tbody className="font-mono-tabular">
            {rows.map((r) => {
              const label = r.segment ?? (r.action ? actionMeta(r.action).label : "Portfolio (pooled)");
              const positive = r.incremental_net_recovery >= 0;
              const significant = r.recovery_rate_diff_z !== null && Math.abs(r.recovery_rate_diff_z) >= SIG_THRESHOLD;
              const lowN = Math.min(r.treatment_n, r.control_n) < LOW_N_THRESHOLD;
              return (
                <tr
                  key={`${r.segment ?? "all"}-${r.action ?? "all"}`}
                  title={lowN ? `Fewer than ${LOW_N_THRESHOLD} invoices per arm -- read with caution` : undefined}
                  className={`border-b border-border/50 last:border-0 transition-colors hover:bg-surface-hover/60 ${lowN ? "opacity-50" : ""}`}
                >
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
                  <td className="px-4 py-3 text-right">
                    <span className={significant ? "text-status-success" : "text-text-faint"}>
                      {r.recovery_rate_diff_z !== null ? r.recovery_rate_diff_z.toFixed(2) : "n/a"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
