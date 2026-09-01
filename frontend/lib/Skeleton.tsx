export function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-2 ${className ?? ""}`} />;
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="overflow-hidden rounded-2xl border border-border">
        <div className="space-y-px bg-border">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex gap-4 bg-surface px-4 py-3.5">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 flex-1" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
