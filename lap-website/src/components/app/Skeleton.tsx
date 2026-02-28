/** Shimmer skeleton primitives for loading states */

export function SkeletonBox({ className = '' }: { className?: string }) {
  return <div className={`bg-steel/10 rounded animate-pulse ${className}`} />;
}

export function SkeletonStatCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" role="status" aria-label="Loading statistics">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="bg-concrete rounded-lg border border-steel/20 p-4">
          <SkeletonBox className="h-3 w-20 mb-2" />
          <SkeletonBox className="h-8 w-16" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCardGrid({ count = 6, cols = 3 }: { count?: number; cols?: 2 | 3 }) {
  const gridClass = cols === 2
    ? 'grid grid-cols-1 md:grid-cols-2 gap-4'
    : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4';
  return (
    <div className={gridClass} role="status" aria-label="Loading content">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="bg-concrete rounded-lg border border-steel/20 p-5">
          <SkeletonBox className="h-5 w-3/4 mb-2" />
          <SkeletonBox className="h-3 w-1/2 mb-3" />
          <div className="flex gap-4 mt-3">
            <SkeletonBox className="h-3 w-12" />
            <SkeletonBox className="h-3 w-12" />
            <SkeletonBox className="h-3 w-12" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SkeletonTableRows({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden" role="status" aria-label="Loading table">
      {/* Header */}
      <div className="flex gap-4 px-4 py-3 border-b border-steel/10">
        {Array.from({ length: cols }, (_, i) => (
          <SkeletonBox key={i} className="h-3 w-16 flex-1" />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-4 px-4 py-3 border-b border-steel/5 last:border-0">
          {Array.from({ length: cols }, (_, c) => (
            <SkeletonBox key={c} className={`h-3 flex-1 ${c === 0 ? 'w-20' : 'w-12'}`} />
          ))}
        </div>
      ))}
    </div>
  );
}
