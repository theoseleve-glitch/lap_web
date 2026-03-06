'use client';

import { useEffect } from 'react';
import { initWebVitals } from '@/lib/web-vitals';
import { getFlag } from '@/lib/feature-flags';

/**
 * Client component that initializes Web Vitals collection on mount.
 * Gated behind the web_vitals feature flag.
 */
export function WebVitalsInit() {
  useEffect(() => {
    if (getFlag('web_vitals')) {
      initWebVitals();
    }
  }, []);

  return null;
}
