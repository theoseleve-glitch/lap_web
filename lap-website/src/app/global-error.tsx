'use client';

import { useEffect } from 'react';
import { logger } from '@/lib/logger';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    logger.error('Global error:', error);
  }, [error]);

  return (
    <html lang="en">
      <body className="bg-asphalt text-chalk min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md px-4">
          <h1 className="text-4xl font-bold text-safety-red mb-3">Something went wrong</h1>
          <p className="text-steel mb-6">
            A critical error occurred. Please try refreshing the page.
          </p>
          {error.digest && (
            <p className="text-steel/50 text-xs tracking-wider mb-6">
              Ref: {error.digest}
            </p>
          )}
          <button
            type="button"
            onClick={reset}
            className="px-6 py-2 bg-gold text-asphalt font-bold rounded hover:bg-gold/90 transition-colors"
          >
            Try Again
          </button>
        </div>
      </body>
    </html>
  );
}
