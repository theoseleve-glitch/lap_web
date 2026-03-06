'use client';

import { useNetworkStatus } from '@/hooks/useNetworkStatus';

/**
 * Banner displayed when the user is offline.
 * Fixed at top, non-blocking. Disappears when back online.
 */
export function OfflineBanner() {
  const online = useNetworkStatus();

  if (online) return null;

  return (
    <div
      role="alert"
      className="fixed top-0 inset-x-0 z-50 bg-pit-orange text-carbon text-center py-2 px-4 font-telemetry text-xs tracking-wider uppercase"
    >
      You are offline — viewing cached data
    </div>
  );
}
