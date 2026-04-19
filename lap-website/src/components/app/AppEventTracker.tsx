'use client';

import { usePageView } from '@/hooks/usePageView';

export function AppEventTracker() {
  usePageView();
  return null;
}
