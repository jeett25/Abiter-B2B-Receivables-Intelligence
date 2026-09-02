import RadialGauge from "@/app/RadialGauge";
import { EvaluationSummary } from "@/lib/types";
import { Card } from "@/lib/ui";

// Recovered-invoice counts are a direct arithmetic derivation of the two
// real numbers the API already returns (recovery_rate * n_invoices) -- not
// a new fact, just the same percentage expressed as a count so the bottom
// row has something concrete to show instead of empty space.
export default function RecoveryGauges({ baseline, engine }: { baseline: EvaluationSummary; engine: EvaluationSummary }) {
  const deltaPts = (engine.recovery_rate - baseline.recovery_rate) * 100;

  return (
    <Card className="flex h-full flex-col p-5 sm:p-6">
      <div className="label !text-text-muted">Recovery rate</div>

      <div className="flex flex-1 flex-col items-center justify-center gap-5 py-2">
        <div className="flex items-center justify-center gap-10">
          <div className="flex flex-col items-center gap-2.5">
            <RadialGauge value={baseline.recovery_rate} size={136} strokeWidth={11} color="var(--color-status-wait)" />
            <div className="max-w-[9.5rem] text-center text-[11px] leading-snug text-text-muted">{baseline.strategy_name}</div>
          </div>
          <div className="flex flex-col items-center gap-2.5">
            <RadialGauge value={engine.recovery_rate} size={136} strokeWidth={11} color="var(--color-accent)" />
            <div className="max-w-[9.5rem] text-center text-[11px] leading-snug text-accent-text">{engine.strategy_name}</div>
          </div>
        </div>
        <div className="text-center text-xs text-text-faint">
          <span className={deltaPts >= 0 ? "text-status-success" : "text-status-danger"}>
            {deltaPts >= 0 ? "+" : ""}
            {deltaPts.toFixed(1)} pts
          </span>{" "}
          vs. {baseline.strategy_name.toLowerCase()}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 border-t border-border pt-4 text-center">
        <div>
          <div className="font-mono-tabular text-sm text-text-muted">
            {Math.round(baseline.recovery_rate * baseline.n_invoices)} / {baseline.n_invoices}
          </div>
          <div className="mt-0.5 text-[10px] text-text-faint">invoices recovered</div>
        </div>
        <div>
          <div className="font-mono-tabular text-sm text-accent-text">
            {Math.round(engine.recovery_rate * engine.n_invoices)} / {engine.n_invoices}
          </div>
          <div className="mt-0.5 text-[10px] text-text-faint">invoices recovered</div>
        </div>
      </div>
    </Card>
  );
}
