import Link from "next/link";
import { DemoFixture } from "@/lib/types";

// Plain <details>/<summary> disclosure -- needs no client JS, works
// everywhere. `fixtures` is empty when GET /api/demo-fixtures failed (see
// layout.tsx) -- the two filter-based links below still work regardless,
// since they don't depend on that endpoint at all.
export default function DemoCaseMenu({ fixtures }: { fixtures: DemoFixture[] }) {
  return (
    <details style={{ display: "inline-block", position: "relative" }}>
      <summary style={{ cursor: "pointer", display: "inline" }}>Load demo case</summary>
      <ul
        style={{
          position: "absolute",
          background: "#111",
          border: "1px solid #888",
          padding: "0.5em 1em",
          listStyle: "none",
          margin: "0.25em 0 0",
          zIndex: 10,
          whiteSpace: "nowrap",
        }}
      >
        {fixtures.map((f) => (
          <li key={f.key}>
            <Link href={`/invoices/${f.invoice_id}`}>{f.label}</Link>{" "}
            <span style={{ fontSize: "0.8em", color: "#888" }}>
              ({f.invoice_number}, expects {f.expected_action})
            </span>
          </li>
        ))}
        <li>
          <Link href="/invoices?current_state=dispute_review">Dispute</Link>{" "}
          <span style={{ fontSize: "0.8em", color: "#888" }}>(filtered list -- no single pinned fixture, pick any)</span>
        </li>
        <li>
          <Link href="/invoices?current_state=closed_abandoned">Abandoned</Link>{" "}
          <span style={{ fontSize: "0.8em", color: "#888" }}>
            (verified: 0 live invoices resolve here today -- see app/agent/DECISIONS.md, not a bug)
          </span>
        </li>
      </ul>
    </details>
  );
}
