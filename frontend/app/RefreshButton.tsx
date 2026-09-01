"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

// router.refresh() clears the Client Cache for the current route and
// re-fetches/re-renders it from the server -- unlike a <Link> to the exact
// same URL, which the router may treat as a no-op since it's already there.
//
// It genuinely gives NO visible signal on its own when the underlying data
// hasn't changed since the last load (the re-render is real, it just looks
// identical) -- wrapped in useTransition so the button can show
// "Refreshing..." while it's in flight, then a "Last refreshed" timestamp
// once it resolves, so a click always has some visible confirmation even
// when the data itself didn't move.
export default function RefreshButton() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const wasPending = useRef(false);

  useEffect(() => {
    if (wasPending.current && !isPending) {
      setLastRefreshed(new Date().toLocaleTimeString("en-IN"));
    }
    wasPending.current = isPending;
  }, [isPending]);

  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <button
        type="button"
        onClick={() => startTransition(() => router.refresh())}
        disabled={isPending}
        className="rounded-lg border border-border bg-surface px-2.5 py-1 font-medium text-text-muted hover:text-text hover:border-border-strong transition-colors disabled:opacity-60"
      >
        {isPending ? "Refreshing…" : "Refresh"}
      </button>
      {lastRefreshed && <span className="text-text-faint">Last refreshed {lastRefreshed}</span>}
    </span>
  );
}
