'use client';

import { useEffect, useMemo } from 'react';
import { Sentry } from '@/lib/sentry';
import { logger } from '@/lib/logger';

function isHydrationError(err: Error): boolean {
  const msg = err.message ?? '';
  return (
    msg.includes('Hydration') ||
    msg.includes('hydrat') ||
    msg.includes('server-rendered') ||
    msg.includes('Text content does not match') ||
    msg.includes('did not match')
  );
}

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const hydration = useMemo(() => isHydrationError(error), [error]);

  useEffect(() => {
    logger.error('Unhandled error:', error);
    Sentry?.captureException(error, { tags: { hydration: hydration ? 'yes' : 'no' } });
  }, [error, hydration]);

  // Auto-recover from hydration mismatches by forcing a full page reload
  useEffect(() => {
    if (hydration) {
      const timer = setTimeout(() => window.location.reload(), 2000);
      return () => clearTimeout(timer);
    }
  }, [hydration]);

  if (hydration) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-asphalt">
        <div className="text-center max-w-md px-4">
          <h1 className="font-monument text-2xl text-marshal-yellow mb-3">Refreshing&hellip;</h1>
          <p className="text-steel font-body mb-4 text-sm">
            A rendering mismatch was detected. The page will reload automatically.
          </p>
          <div className="w-6 h-6 mx-auto border-2 border-steel/30 border-t-marshal-yellow rounded-full animate-spin" />
        </div>
      </div>
    );
  }

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
