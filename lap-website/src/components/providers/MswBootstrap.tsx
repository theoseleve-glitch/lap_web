'use client';
import { useEffect } from 'react';

export function MswBootstrap() {
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_USE_MSW !== '1') return;
    let cancelled = false;
    (async () => {
      const { worker } = await import('@/mocks/browser');
      if (cancelled) return;
      await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return null;
}
