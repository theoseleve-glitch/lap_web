/**
 * ErrorBlock — canonical error state with retry.
 *
 * Every API error, failed load, or unexpected state renders this.
 * Explains what happened, why, and what the user can do next.
 * Premium feel — not a raw red text dump.
 *
 * Usage:
 *   <ErrorBlock
 *     title="Failed to load sessions"
 *     description="The server returned an unexpected error."
 *     onRetry={() => refetch()}
 *   />
 */

export interface ErrorBlockProps {
  title?: string;
  description?: string;
  /** Retry handler. If omitted, no retry button shown. */
  onRetry?: () => void;
  /** Optional support link. */
  supportHref?: string;
  className?: string;
}

export function ErrorBlock({
  title = 'Something went wrong',
  description,
  onRetry,
  supportHref = '/app/account/support',
  className = '',
}: ErrorBlockProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 px-6 text-center ${className}`}>
      <div className="w-12 h-12 rounded-full border border-safety-red/20 flex items-center justify-center mb-4">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-safety-red/60"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <h3 className="text-sm font-monument text-chalk mb-1">{title}</h3>
      {description && (
        <p className="text-xs font-body text-steel max-w-sm mb-4">{description}</p>
      )}
      <div className="flex items-center gap-3">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center px-4 py-2 text-xs font-telemetry uppercase tracking-[0.1em] text-chalk border border-steel/20 rounded-lg hover:bg-steel/8 transition-colors"
          >
            Try again
          </button>
        )}
        <a
          href={supportHref}
          className="text-[10px] font-telemetry text-steel/60 hover:text-chalk underline underline-offset-2 transition-colors"
        >
          Contact support
        </a>
      </div>
    </div>
  );
}
