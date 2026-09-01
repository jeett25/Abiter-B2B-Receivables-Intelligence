"use client";

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
      <h2>Something went wrong loading invoices.</h2>
      <p>{error.message}</p>
      <button onClick={() => retry()}>Try again</button>
    </div>
  );
}
