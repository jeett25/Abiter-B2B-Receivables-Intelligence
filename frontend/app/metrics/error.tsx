"use client";

import { ErrorPanel } from "@/lib/ui";

// Safety net for genuinely unexpected exceptions -- the expected failure
// (getMetrics/getAttribution rejecting) is already handled inline in
// page.tsx's own try/catch, same convention as invoices/error.tsx.
export default function MetricsError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-text">Something went wrong loading metrics.</h2>
      <ErrorPanel message={error.message} retryHref="/metrics" />
      <button
        onClick={() => retry()}
        className="mt-3 rounded-lg border border-border px-3 py-1.5 text-sm text-text-muted hover:text-text hover:border-border-strong transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
