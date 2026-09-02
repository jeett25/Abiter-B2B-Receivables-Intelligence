"use client";

import { ErrorPanel } from "@/lib/ui";

// Safety net for a genuinely unexpected exception. Observability itself
// fetches nothing (static, documented figures -- see page.tsx's own
// comment), so this should never actually trigger in practice; it exists
// for the same reason every other console route has one: consistency, not
// because a failure mode was found here.
export default function ObservabilityError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-text">Something went wrong loading this page.</h2>
      <ErrorPanel message={error.message} retryHref="/observability" />
      <button
        onClick={() => retry()}
        className="mt-3 rounded-lg border border-border px-3 py-1.5 text-sm text-text-muted hover:text-text hover:border-border-strong transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
