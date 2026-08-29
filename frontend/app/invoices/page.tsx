import Link from "next/link";
import { mockInvoices } from "@/lib/mockData";

// Screen 1 (master doc Day 3): overdue invoices, status, recoverability
// score, next action. Data source is lib/mockData.ts for now -- Day 6 swaps
// this for a real API call against the same InvoiceSummary shape.
export default function InvoicesPage() {
  return (
    <div>
      <h1>Overdue Invoices</h1>
      <table border={1} cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th>Invoice #</th>
            <th>Customer</th>
            <th>Amount</th>
            <th>Due Date</th>
            <th>Status</th>
            <th>Recoverability</th>
            <th>Next Action</th>
          </tr>
        </thead>
        <tbody>
          {mockInvoices.map((invoice) => (
            <tr key={invoice.invoice_id}>
              <td>
                <Link href={`/invoices/${invoice.invoice_id}`}>{invoice.invoice_number}</Link>
              </td>
              <td>{invoice.customer_name}</td>
              <td>Rs.{invoice.amount.toLocaleString("en-IN")}</td>
              <td>{invoice.due_date}</td>
              <td>{invoice.current_state}</td>
              <td>{(invoice.recoverability_score * 100).toFixed(0)}%</td>
              <td>{invoice.next_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
