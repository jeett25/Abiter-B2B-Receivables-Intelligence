"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AttributionHeadline } from "@/lib/types";
import { Card, formatCurrency, formatPercent } from "@/lib/ui";

function groupColor(group: string): string {
  return group === "Treatment" ? "var(--color-accent)" : "var(--color-status-wait)";
}

export default function AttributionCompareChart({ headline }: { headline: AttributionHeadline }) {
  const rateData = [
    { group: "Control", value: headline.control_recovery_rate },
    { group: "Treatment", value: headline.treatment_recovery_rate },
  ];
  const amountData = [
    { group: "Control", value: headline.control_recovered_amount },
    { group: "Treatment", value: headline.treatment_recovered_amount },
  ];

  return (
    <Card className="p-5 sm:p-6">
      <div className="label mb-4 !text-text-muted">
        Treatment vs. control — randomized holdout ({headline.treatment_n} treated / {headline.control_n} control)
      </div>
      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <div className="mb-2 text-[11px] text-text-faint">Recovery rate</div>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rateData} layout="vertical" margin={{ left: 8, right: 32 }}>
                <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" horizontal={false} />
                <XAxis
                  type="number"
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  stroke="var(--color-text-faint)"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: "var(--color-border)" }}
                />
                <YAxis type="category" dataKey="group" stroke="var(--color-text-muted)" fontSize={12} tickLine={false} axisLine={false} width={64} />
                <Tooltip
                  cursor={{ fill: "var(--color-surface-hover)" }}
                  contentStyle={{
                    background: "var(--color-surface-2)",
                    border: "1px solid var(--color-border-strong)",
                    borderRadius: 10,
                    fontSize: 12,
                  }}
                  formatter={(value) => formatPercent(Number(value))}
                />
                <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={36}>
                  {rateData.map((d) => (
                    <Cell key={d.group} fill={groupColor(d.group)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <div className="mb-2 text-[11px] text-text-faint">Recovered amount</div>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={amountData} layout="vertical" margin={{ left: 8, right: 32 }}>
                <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" horizontal={false} />
                <XAxis
                  type="number"
                  tickFormatter={(v: number) => `₹${(v / 100000).toFixed(1)}L`}
                  stroke="var(--color-text-faint)"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: "var(--color-border)" }}
                />
                <YAxis type="category" dataKey="group" stroke="var(--color-text-muted)" fontSize={12} tickLine={false} axisLine={false} width={64} />
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
                <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={36}>
                  {amountData.map((d) => (
                    <Cell key={d.group} fill={groupColor(d.group)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </Card>
  );
}
