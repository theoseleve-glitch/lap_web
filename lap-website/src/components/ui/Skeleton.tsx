/**
 * Skeleton loading primitive — replaces spinners for content placeholders.
 *
 * Usage:
 *   <Skeleton className="h-4 w-32" />              — text line
 *   <Skeleton className="h-10 w-full" />            — input field
 *   <Skeleton className="h-48 w-full rounded-2" />  — card
 *   <Skeleton circle className="h-10 w-10" />       — avatar
 */

interface SkeletonProps {
  className?: string;
  circle?: boolean;
}

export function Skeleton({ className = '', circle = false }: SkeletonProps) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={`
        animate-pulse bg-steel/10
        ${circle ? 'rounded-full' : 'rounded-2'}
        ${className}
      `}
    />
  );
}

interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export function SkeletonText({ lines = 3, className = '' }: SkeletonTextProps) {
  return (
    <div className={`space-y-2 ${className}`} role="status" aria-label="Loading text">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'}`}
        />
      ))}
    </div>
  );
}
