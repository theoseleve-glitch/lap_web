'use client';

import { useState, useEffect } from 'react';
import { getFlag, loadFlags, type FeatureFlags } from '@/lib/feature-flags';

/**
 * React hook for checking a feature flag.
 * Triggers an async load on mount, then returns the cached value synchronously.
 */
export function useFeatureFlag(flag: keyof FeatureFlags): boolean {
  const [value, setValue] = useState(() => getFlag(flag));

  useEffect(() => {
    let cancelled = false;
    loadFlags().then(() => {
      if (!cancelled) setValue(getFlag(flag));
    });
    return () => { cancelled = true; };
  }, [flag]);

  return value;
}
