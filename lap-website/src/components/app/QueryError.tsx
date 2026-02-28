'use client';

interface QueryErrorProps {
  message?: string;
  onRetry?: () => void;
}

export function QueryError({
  message = 'Something went wrong loading this data.',
  onRetry,
}: QueryErrorProps) {
  return (
    <div className="bg-concrete rounded-lg border border-safety-red/20 p-8 text-center">
      <div className="text-safety-red font-telemetry text-3xl mb-3" aria-hidden="true">
        !
      </div>
      <p className="text-chalk font-body text-sm mb-1">Failed to load</p>
      <p className="text-steel font-body text-xs max-w-md mx-auto mb-4">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="px-4 py-2 bg-safety-red/10 text-safety-red border border-safety-red/30 font-telemetry text-xs rounded hover:bg-safety-red/20 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
