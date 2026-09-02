"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { EvaluationSummary } from "@/lib/types";
import { Card } from "@/lib/ui";

// status-wait and text-faint (the lib/ui-consistent choice) render as two
// near-identical greys at a glance -- confirmed via user testing, not just
// a contrast-ratio check. Traded strict tone-mapping consistency for actual
// glanceable distinction: amber for Wait, red for Stop, accent blue for
// Intervened -- three unambiguous hues, at the cost of "Stop" no longer
// sharing lib/ui's neutral-tone convention used elsewhere on the console.
const COLORS = {
  wait: "var(--color-status-escalate)",
  interventions: "var(--color-accent)",
  stop: "var(--color-status-danger)",
};

function toData(s: EvaluationSummary) {
  return [
    { name: "Wait", value: s.n_wait, color: COLORS.wait },
    { name: "Intervened", value: s.n_interventions, color: COLORS.interventions },
    { name: "Stop", value: s.n_stop, color: COLORS.stop },
  ].filter((d) => d.value > 0);
}

function Donut({ summary }: { summary: EvaluationSummary }) {
  const data = toData(summary);
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="label !text-text-muted">{summary.strategy_name}</div>
      <div className="h-56 w-56">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius={62}
              outerRadius={92}
              paddingAngle={data.length > 1 ? 3 : 0}
              strokeWidth={0}
            >
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--color-surface-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: 10,
                fontSize: 12,
              }}
              formatter={(value, name) => [`${value} invoices`, name]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1.5 text-xs text-text-muted">
        {data.map((d) => (
          <span key={d.name} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
            {d.name} · {d.value}
          </span>
        ))}
      </div>
    </div>
  );
}

// Grid, not flex -- the previous flex-row-with-inner-padding layout let
// each donut's wrapper shrink to its own content width, leaving the
// second half of the card visibly empty. A 2-col grid forces both cells
// to actually claim half the row regardless of how narrow their content is.
export default function DecisionMixChart({ baseline, engine }: { baseline: EvaluationSummary; engine: EvaluationSummary }) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="label mb-6 !text-text-muted">Decision mix — where each strategy sends the live pool</div>
      <div className="grid gap-8 sm:grid-cols-2">
        <div className="flex justify-center sm:border-r sm:border-border sm:pr-4">
          <Donut summary={baseline} />
        </div>
        <div className="flex justify-center">
          <Donut summary={engine} />
        </div>
      </div>
    </Card>
  );
}
