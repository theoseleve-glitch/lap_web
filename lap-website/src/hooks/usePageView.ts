'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { trackEvent } from './useTrackEvent';

export function usePageView(): void {
  const pathname = usePathname();
  const prevPath = useRef<string | null>(null);
  const enterTime = useRef<number>(Date.now());

  useEffect(() => {
    if (!pathname.startsWith('/app')) return;

    const now = Date.now();
    const previous = prevPath.current;

    // Send time-on-page for the previous /app path (if duration > 500ms)
    if (previous !== null) {
      const duration = now - enterTime.current;
      if (duration > 500) {
        trackEvent('page.time_on_page', { duration_ms: duration }, previous);
      }
    }

    // Determine referrer: previous /app path or document referrer
    const referrer =
      previous !== null
        ? previous
        : typeof document !== 'undefined'
          ? document.referrer
          : '';

    trackEvent('page.view', { referrer }, pathname);

    prevPath.current = pathname;
    enterTime.current = now;
  }, [pathname]);
}
