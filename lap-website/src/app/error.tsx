'use client';

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log to analytics/error tracking
    console.error('Unhandled error:', error);
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-asphalt">
      <div className="text-center max-w-md px-4">
        <h1 className="font-monument text-4xl text-safety-red mb-3">Something went wrong</h1>
        <p className="text-steel font-body mb-6">
          An unexpected error occurred. This has been logged and we&rsquo;ll look into it.
        </p>
        {error.digest && (
          <p className="text-steel/50 font-telemetry text-[10px] tracking-wider mb-6">
            Error reference: {error.digest}
          </p>
        )}
        <button
          onClick={reset}
          className="border border-pit-orange text-pit-orange px-6 py-2.5 font-telemetry text-sm uppercase tracking-wider hover:bg-pit-orange/10 transition-colors"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
