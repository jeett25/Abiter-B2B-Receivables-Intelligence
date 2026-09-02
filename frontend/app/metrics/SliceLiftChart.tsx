"use client";

import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, formatCurrency } from "@/lib/ui";

export default function SliceLiftChart({ title, data }: { title: string; data: { label: string; value: number }[] }) {
  const sorted = [...data].sort((a, b) => b.value - a.value);
  if (sorted.length === 0) return null;

  return (
    <Card className="p-5 sm:p-6">
      <div className="label mb-4 !text-text-muted">{title}</div>
      <div style={{ height: Math.max(140, sorted.length * 42) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={sorted} layout="vertical" margin={{ left: 8, right: 40 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" horizontal={false} />
            <XAxis
              type="number"
              tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`}
              stroke="var(--color-text-faint)"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: "var(--color-border)" }}
            />
            <YAxis type="category" dataKey="label" stroke="var(--color-text-muted)" fontSize={12} tickLine={false} axisLine={false} width={104} />
            <ReferenceLine x={0} stroke="var(--color-border-strong)" />
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
            <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={22}>
              {sorted.map((d) => (
                <Cell key={d.label} fill={d.value >= 0 ? "var(--color-status-success)" : "var(--color-status-danger)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
