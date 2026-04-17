'use client';

import Link from 'next/link';

export function EmptyBundleState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <p className="text-lg font-monument text-chalk mb-2">No sessions yet</p>
      <p className="text-sm font-body text-steel mb-6 max-w-sm">
        Upload your first session bundle to start analyzing track surface, grip levels,
        and racing strategy.
      </p>
      <Link
        href="/app/bundles/upload"
        className="bg-gold text-white font-telemetry text-sm px-5 py-2.5 rounded-lg hover:bg-gold/80 transition-colors"
      >
        Upload Session
      </Link>
    </div>
  );
}
