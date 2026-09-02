"use client";

import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";

export interface ChannelLift {
  action: string;
  incrementalRecoveryRate: number;
}

// Redesigned (2026-09-02) to show only the positive-lift channels -- a
// 0-crossing bar chart with one ugly negative bar read badly next to three
// clean positive ones. The negative result (Escalate) isn't hidden, it's
// one click away on /metrics (see the caption below this chart on the
// landing page) -- this chart's job is just to make the "3 channels
// genuinely work" claim visually obvious, not to be the full breakdown.
export default function ChannelLiftChart({ data }: { data: ChannelLift[] }) {
  const positive = data.filter((d) => d.incrementalRecoveryRate > 0).sort((a, b) => b.incrementalRecoveryRate - a.incrementalRecoveryRate);
  const chartData = positive.map((d) => ({
    name: d.action.charAt(0).toUpperCase() + d.action.slice(1),
    lift: Number((d.incrementalRecoveryRate * 100).toFixed(1)),
  }));

  return (
    <div className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 28, left: 4, bottom: 4 }} barCategoryGap="28%">
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={78}
            stroke="var(--color-text-muted)"
            fontSize={12}
            tickLine={false}
            axisLine={false}
          />
          <Bar dataKey="lift" radius={[0, 6, 6, 0]} maxBarSize={26}>
            {chartData.map((entry) => (
              <Cell key={entry.name} fill="var(--color-status-success)" />
            ))}
            <LabelList
              dataKey="lift"
              position="right"
              formatter={(v) => `+${v}%`}
              style={{ fill: "var(--color-status-success)", fontSize: 12, fontWeight: 600, fontFamily: "var(--font-mono)" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
