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

/**
 * Session detail skeleton — matches the actual session detail layout:
 * breadcrumb + header (56px), 4 stat cards (80px), tab bar (48px),
 * chart area (300px), lap table (~250px).
 */
export function SkeletonSessionDetail() {
  return (
    <div role="status" aria-label="Loading session detail">
      {/* Breadcrumb + title area */}
      <div className="mb-6">
        <SkeletonBox className="h-3 w-20 mb-2" />
        <SkeletonBox className="h-8 w-64 mb-2" />
        <SkeletonBox className="h-4 w-48" />
      </div>

      {/* Stat cards row — 4 cards, each ~80px tall */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="bg-concrete rounded-xl border border-steel/10 p-4" style={{ minHeight: '80px' }}>
            <SkeletonBox className="h-3 w-16 mb-3" />
            <SkeletonBox className="h-7 w-20" />
          </div>
        ))}
      </div>

      {/* Tab bar — 48px */}
      <div className="flex gap-1 mb-6 border-b border-steel/10" style={{ minHeight: '48px' }}>
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonBox key={i} className="h-4 w-20 mb-3" />
        ))}
      </div>

      {/* Chart area — 300px reserved for speed trace / GG explorer */}
      <div className="bg-concrete rounded-xl border border-steel/10 mb-6" style={{ minHeight: '300px' }}>
        <div className="p-4">
          <SkeletonBox className="h-4 w-32 mb-4" />
          <SkeletonBox className="h-full w-full" style={{ minHeight: '240px' }} />
        </div>
      </div>

      {/* Score bars */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-5 mb-6">
        <SkeletonBox className="h-5 w-28 mb-4" />
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="mb-3">
            <div className="flex justify-between mb-1">
              <SkeletonBox className="h-3 w-20" />
              <SkeletonBox className="h-3 w-12" />
            </div>
            <SkeletonBox className="h-2.5 w-full rounded-full" />
          </div>
        ))}
      </div>

      {/* Lap table */}
      <SkeletonTableRows rows={6} cols={5} />
    </div>
  );
}

/**
 * Compare sessions skeleton — matches the compare layout:
 * header (48px), selector bar (~72px), 2-col metadata cards,
 * score comparison (240px), chart panel (300px), lap table.
 */
export function SkeletonCompareView() {
  return (
    <div role="status" aria-label="Loading comparison">
      {/* Header */}
      <div className="mb-6">
        <SkeletonBox className="h-7 w-52 mb-2" />
        <SkeletonBox className="h-4 w-96" />
      </div>

      {/* Session selectors bar */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-5 mb-6" style={{ minHeight: '72px' }}>
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <SkeletonBox className="h-3 w-16 mb-2" />
            <SkeletonBox className="h-10 w-full rounded" />
          </div>
          <SkeletonBox className="h-10 w-10 shrink-0 rounded-lg" />
          <div className="flex-1">
            <SkeletonBox className="h-3 w-16 mb-2" />
            <SkeletonBox className="h-10 w-full rounded" />
          </div>
        </div>
      </div>

      {/* Score comparison cards — 2x2 grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="bg-concrete rounded-xl border border-steel/10 p-4" style={{ minHeight: '120px' }}>
            <SkeletonBox className="h-4 w-20 mb-3" />
            <SkeletonBox className="h-2 w-full rounded-full mb-2" />
            <SkeletonBox className="h-2 w-full rounded-full" />
          </div>
        ))}
      </div>

      {/* Chart panel placeholder */}
      <div className="bg-concrete rounded-xl border border-steel/10 mb-6" style={{ minHeight: '300px' }}>
        <div className="p-4">
          <SkeletonBox className="h-4 w-32 mb-4" />
          <SkeletonBox className="h-full w-full" style={{ minHeight: '240px' }} />
        </div>
      </div>

      {/* Lap comparison table */}
      <SkeletonTableRows rows={6} cols={4} />
    </div>
  );
}
