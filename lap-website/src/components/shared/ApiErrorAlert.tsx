'use client';

interface ApiErrorAlertProps {
  message: string;
  requestId?: string | null;
  className?: string;
}

/**
 * Standard error alert that shows the error message and, when available,
 * the backend request_id for support correlation.
 */
export function ApiErrorAlert({ message, requestId, className }: ApiErrorAlertProps) {
  return (
    <div
      className={`p-3 rounded-lg bg-safety-red/10 border border-safety-red/20 text-safety-red text-sm font-body ${className ?? ''}`}
      role="alert"
    >
      {message}
      {requestId && (
        <p className="mt-1 text-steel/50 text-[10px] tracking-wider font-telemetry">
          Ref: {requestId}
        </p>
      )}
    </div>
  );
}
