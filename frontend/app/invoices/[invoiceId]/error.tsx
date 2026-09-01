"use client";

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
      <h2>Something went wrong loading this invoice.</h2>
      <p>{error.message}</p>
      <button onClick={() => retry()}>Try again</button>
    </div>
  );
}
