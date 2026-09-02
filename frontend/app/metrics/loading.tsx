import { Skeleton } from "@/lib/Skeleton";

// Metrics is the one console page with no skeleton yet -- worth having on
// its own: the hosted backend's free-tier cold start is ~28s on a first
// request (see CLAUDE.md subtask 9), and this page fires two fetches
// (getMetrics + getAttribution) in parallel on every load.
export default function Loading() {
  return (
    <div className="space-y-10">
      <div className="space-y-2.5">
        <Skeleton className="h-8 w-96 max-w-full" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-card" />
        ))}
      </div>

      <div className="space-y-4">
        <Skeleton className="h-4 w-56" />
        <div className="grid gap-4 md:grid-cols-[0.85fr_1.6fr]">
          <Skeleton className="h-80 w-full rounded-card" />
          <Skeleton className="h-80 w-full rounded-card" />
        </div>
        <Skeleton className="h-64 w-full rounded-card" />
        <Skeleton className="h-52 w-full rounded-card" />
      </div>

      <div className="space-y-4">
        <Skeleton className="h-4 w-72" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full rounded-card" />
          ))}
        </div>
        <Skeleton className="h-52 w-full rounded-card" />
      </div>
    </div>
  );
}
