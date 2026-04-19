/**
 * SkeletonTable — shimmer-loading placeholder for data tables.
 *
 * Shows during the initial fetch so the user sees structure + motion
 * instead of a blank void or a centered spinner. Matches the visual
 * rhythm of the real table (same row height, column count, padding).
 *
 * Usage:
 *   {isLoading ? <SkeletonTable rows={8} cols={5} /> : <DataTable ... />}
 */

interface SkeletonTableProps {
  rows?: number;
  cols?: number;
  /** Show a header row. Default true. */
  header?: boolean;
  className?: string;
}

function SkeletonBar({ width = '100%' }: { width?: string }) {
  return (
    <div
      className="h-3 rounded bg-steel/8 animate-pulse"
      style={{ width }}
    />
  );
}

export function SkeletonTable({
  rows = 6,
  cols = 4,
  header = true,
  className = '',
}: SkeletonTableProps) {
  const colWidths = ['65%', '40%', '50%', '35%', '30%', '45%', '55%'];

  return (
    <div className={`w-full ${className}`}>
      {header && (
        <div className="flex items-center gap-4 px-4 py-3 border-b border-steel/8">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="flex-1">
              <SkeletonBar width={colWidths[c % colWidths.length]} />
            </div>
          ))}
        </div>
      )}
      {Array.from({ length: rows }).map((_, r) => (
        <div
          key={r}
          className="flex items-center gap-4 px-4 py-3 border-b border-steel/5"
        >
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="flex-1">
              <SkeletonBar
                width={colWidths[(c + r) % colWidths.length]}
              />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * SkeletonCardGrid — shimmer-loading for card-based layouts.
 */
export function SkeletonCardGrid({
  count = 6,
  className = '',
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-steel/8 p-4 space-y-3 animate-pulse"
          style={{ background: 'linear-gradient(180deg, #080808 0%, #040404 100%)' }}
        >
          <SkeletonBar width="60%" />
          <SkeletonBar width="85%" />
          <SkeletonBar width="40%" />
          <div className="pt-2">
            <SkeletonBar width="30%" />
          </div>
        </div>
      ))}
    </div>
  );
}
