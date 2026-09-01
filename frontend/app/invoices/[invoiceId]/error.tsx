"use client";

import { ErrorPanel } from "@/lib/ui";

// Safety net for genuinely unexpected exceptions -- expected failures
// (fetch errors, 404s) are handled inline in page.tsx.
export default function InvoiceDetailError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-text">Something went wrong loading this invoice.</h2>
      <ErrorPanel message={error.message} retryHref="/invoices" />
      <button
        onClick={() => retry()}
        className="mt-3 rounded-lg border border-border px-3 py-1.5 text-sm text-text-muted hover:text-text hover:border-border-strong transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
