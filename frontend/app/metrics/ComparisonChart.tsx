"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EvaluationSummary } from "@/lib/types";
import { Card, formatCurrency } from "@/lib/ui";

export default function ComparisonChart({ baseline, engine }: { baseline: EvaluationSummary; engine: EvaluationSummary }) {
  const data = [
    {
      metric: "Gross expected",
      Baseline: baseline.gross_expected_recovered,
      Engine: engine.gross_expected_recovered,
    },
    {
      metric: "Cost + friction",
      Baseline: baseline.total_cost + baseline.total_friction,
      Engine: engine.total_cost + engine.total_friction,
    },
    {
      metric: "Net expected",
      Baseline: baseline.net_expected_recovered,
      Engine: engine.net_expected_recovered,
    },
  ];

  return (
    <Card className="p-5 sm:p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-text-muted">Expected recovery, ₹</h2>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: 8, right: 8 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="metric" stroke="var(--color-text-muted)" fontSize={12} tickLine={false} axisLine={{ stroke: "var(--color-border)" }} />
            <YAxis
              stroke="var(--color-text-muted)"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `₹${(v / 100000).toFixed(1)}L`}
            />
            <Tooltip
              cursor={{ fill: "var(--color-surface-hover)" }}
              contentStyle={{
                background: "var(--color-surface-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: 10,
                fontSize: 12,
              }}
              formatter={(value) => formatCurrency(Number(value))}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Baseline" fill="var(--color-status-wait)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="Engine" fill="var(--color-accent)" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
