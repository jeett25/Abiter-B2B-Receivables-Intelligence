"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EvaluationSummary } from "@/lib/types";
import { Card, formatCurrency } from "@/lib/ui";

export default function ComparisonChart({ baseline, engine }: { baseline: EvaluationSummary; engine: EvaluationSummary }) {
  const data = [
    { metric: "Gross expected", Baseline: baseline.gross_expected_recovered, Engine: engine.gross_expected_recovered },
    { metric: "Cost + friction", Baseline: baseline.total_cost + baseline.total_friction, Engine: engine.total_cost + engine.total_friction },
    { metric: "Net expected", Baseline: baseline.net_expected_recovered, Engine: engine.net_expected_recovered },
  ];

  return (
    <Card className="p-5 sm:p-6">
      <div className="label mb-4 !text-text-muted">
        Expected recovery (₹) — {baseline.strategy_name} vs. {engine.strategy_name}
      </div>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ left: 8, right: 8 }} barGap={6}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="metric"
              stroke="var(--color-text-faint)"
              fontSize={11.5}
              tickLine={false}
              axisLine={{ stroke: "var(--color-border)" }}
            />
            <YAxis
              stroke="var(--color-text-faint)"
              fontSize={11}
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
              labelStyle={{ color: "var(--color-text)", marginBottom: 4, fontWeight: 600 }}
              itemStyle={{ color: "var(--color-text)" }}
              formatter={(value) => formatCurrency(Number(value))}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} iconType="circle" iconSize={8} />
            <Bar dataKey="Baseline" name={baseline.strategy_name} fill="var(--color-status-wait)" radius={[6, 6, 0, 0]} maxBarSize={64} />
            <Bar dataKey="Engine" name={engine.strategy_name} fill="var(--color-accent)" radius={[6, 6, 0, 0]} maxBarSize={64} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
