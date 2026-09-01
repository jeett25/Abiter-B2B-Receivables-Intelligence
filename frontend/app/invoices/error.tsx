"use client";

import { ErrorPanel } from "@/lib/ui";

// Safety net for genuinely unexpected exceptions (a bug, not a failed
// fetch -- that's handled inline in page.tsx per Next's own "expected vs
// uncaught errors" guidance). retry() re-renders the segment in place.
export default function InvoicesError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-text">Something went wrong loading invoices.</h2>
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
