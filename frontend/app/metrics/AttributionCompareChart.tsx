"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AttributionHeadline } from "@/lib/types";
import { Card, formatCurrency, formatPercent } from "@/lib/ui";

function groupColor(group: string): string {
  return group === "Treatment" ? "var(--color-accent)" : "var(--color-status-wait)";
}

function MiniBarPanel({
  title,
  data,
  tickFormatter,
  tooltipFormatter,
}: {
  title: string;
  data: { group: string; value: number }[];
  tickFormatter: (v: number) => string;
  tooltipFormatter: (v: number) => string;
}) {
  return (
    <div>
      <div className="mb-2 text-[11px] text-text-faint">{title}</div>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 32 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" horizontal={false} />
            <XAxis
              type="number"
              tickFormatter={tickFormatter}
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
              formatter={(value) => tooltipFormatter(Number(value))}
            />
            <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={36}>
              {data.map((d) => (
                <Cell key={d.group} fill={groupColor(d.group)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
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
  const hasCountData = headline.treatment_count_recovery_rate != null && headline.control_count_recovery_rate != null;
  const countData = hasCountData
    ? [
        { group: "Control", value: headline.control_count_recovery_rate as number },
        { group: "Treatment", value: headline.treatment_count_recovery_rate as number },
      ]
    : [];

  return (
    <Card className="p-5 sm:p-6">
      <div className="label mb-4 !text-text-muted">
        Treatment vs. control — randomized holdout ({headline.treatment_n} treated / {headline.control_n} control)
      </div>
      <div className={`grid gap-6 ${hasCountData ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
        <MiniBarPanel
          title="Recovery rate (₹-weighted)"
          data={rateData}
          tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
          tooltipFormatter={(v) => formatPercent(v)}
        />
        {hasCountData && (
          <MiniBarPanel
            title="Recovery rate (by invoice count)"
            data={countData}
            tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            tooltipFormatter={(v) => formatPercent(v)}
          />
        )}
        <MiniBarPanel
          title="Recovered amount"
          data={amountData}
          tickFormatter={(v) => `₹${(v / 100000).toFixed(1)}L`}
          tooltipFormatter={(v) => formatCurrency(v)}
        />
      </div>
    </Card>
  );
}
