/**
 * Chart loading / empty / error states.
 *
 * Every chart should render exactly one of these inside its ChartBody when
 * data is unavailable. Keeps the visual treatment of those states identical
 * across the analytics UI.
 */

export interface ChartLoadingStateProps {
  message?: string;
}

export function ChartLoadingState({ message = 'Loading…' }: ChartLoadingStateProps) {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="flex items-center gap-2 text-steel font-telemetry text-xs">
        <span className="inline-block w-3 h-3 border border-steel/40 border-t-chalk rounded-full animate-spin" />
        <span className="uppercase tracking-wider">{message}</span>
      </div>
    </div>
  );
}

export interface ChartEmptyStateProps {
  /** What's missing, in user terms. */
  message?: string;
  /** Optional secondary line — what the user can do. */
  hint?: string;
}

export function ChartEmptyState({
  message = 'No data available',
  hint,
}: ChartEmptyStateProps) {
  return (
    <div className="absolute inset-0 flex items-center justify-center px-4">
      <div className="text-center max-w-xs">
        <div className="text-xs font-telemetry text-chalk uppercase tracking-wider mb-1">
          {message}
        </div>
        {hint && (
          <div className="text-[11px] font-telemetry text-steel">{hint}</div>
        )}
      </div>
    </div>
  );
}

export interface ChartErrorStateProps {
  /** Short error summary. */
  message?: string;
  /** Optional retry handler — renders a small retry control. */
  onRetry?: () => void;
}

export function ChartErrorState({
  message = 'Could not load chart',
  onRetry,
}: ChartErrorStateProps) {
  return (
    <div className="absolute inset-0 flex items-center justify-center px-4">
      <div className="text-center">
        <div className="text-xs font-telemetry text-safety-red uppercase tracking-wider mb-2">
          {message}
        </div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="text-[11px] font-telemetry text-steel hover:text-chalk underline underline-offset-2 transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
