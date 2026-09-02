"use client";

import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, formatCurrency } from "@/lib/ui";

// Below this, a slice's treatment/control counts are too small to read the
// bar with any confidence -- e.g. Mid-Market x ESCALATE can be as few as 7
// treatment invoices. Dimmed, not hidden: the number is still real and
// worth seeing, just not worth the same visual weight as a 200-invoice bar.
const LOW_N_THRESHOLD = 15;

export default function SliceLiftChart({ title, data }: { title: string; data: { label: string; value: number; n: number }[] }) {
  const sorted = [...data].sort((a, b) => b.value - a.value);
  if (sorted.length === 0) return null;
  const anyLowN = sorted.some((d) => d.n < LOW_N_THRESHOLD);

  return (
    <Card className="p-5 sm:p-6">
      <div className="label !text-text-muted">{title}</div>
      {anyLowN && (
        <p className="mt-1 mb-3 text-xs text-text-faint">
          Faded bars have fewer than {LOW_N_THRESHOLD} invoices per arm — too small a sample to read confidently.
        </p>
      )}
      <div className={anyLowN ? "mt-3" : "mt-4"} style={{ height: Math.max(140, sorted.length * 42) }}>
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
              itemStyle={{ color: "var(--color-text)" }}
              labelStyle={{ color: "var(--color-text)", fontWeight: 600 }}
              formatter={(value, _name, item) => [formatCurrency(Number(value)), `n=${item.payload.n} per arm`]}
            />
            <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={22}>
              {sorted.map((d) => (
                <Cell
                  key={d.label}
                  fill={d.value >= 0 ? "var(--color-status-success)" : "var(--color-status-danger)"}
                  fillOpacity={d.n < LOW_N_THRESHOLD ? 0.35 : 1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
