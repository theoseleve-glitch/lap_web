/**
 * ChartSyncProvider.tsx — Distance-based hover sync context.
 *
 * Wraps chart groups. Children use useChartSync() to get/set the current
 * hover distance. Different syncId values create independent sync buses.
 */
'use client';

import { createContext, useContext, useMemo, useCallback } from 'react';
import { useChartHoverStore } from '@/lib/chart-hover-store';

interface ChartSyncContextValue {
  syncId: string;
  hoverDistance: number | null;
  hoverSource: string | null;
  setHover: (distance: number, source: string) => void;
  clearHover: () => void;
}

const ChartSyncContext = createContext<ChartSyncContextValue | null>(null);

interface ChartSyncProviderProps {
  children: React.ReactNode;
  /** Isolates sync groups (e.g. "compare-left" vs "compare-right") */
  syncId?: string;
}

export function ChartSyncProvider({ children, syncId = 'default' }: ChartSyncProviderProps) {
  const hoverDistance = useChartHoverStore((s) => s.hoverDistance);
  const hoverSource = useChartHoverStore((s) => s.hoverSource);
  const storeSetHover = useChartHoverStore((s) => s.setHover);
  const storeClearHover = useChartHoverStore((s) => s.clearHover);

  const setHover = useCallback(
    (distance: number, source: string) => {
      storeSetHover(distance, `${syncId}:${source}`);
    },
    [storeSetHover, syncId],
  );

  const clearHover = useCallback(() => {
    storeClearHover();
  }, [storeClearHover]);

  // Filter hover events by syncId prefix
  const isOwnSync = hoverSource?.startsWith(`${syncId}:`) ?? false;

  const value = useMemo(
    () => ({
      syncId,
      hoverDistance: isOwnSync ? hoverDistance : null,
      hoverSource: isOwnSync ? hoverSource : null,
      setHover,
      clearHover,
    }),
    [syncId, isOwnSync, hoverDistance, hoverSource, setHover, clearHover],
  );

  return (
    <ChartSyncContext.Provider value={value}>
      {children}
    </ChartSyncContext.Provider>
  );
}

/**
 * useChartSync — access the nearest ChartSyncProvider context.
 * Falls back to the global Zustand store when used outside a provider.
 */
export function useChartSync() {
  const ctx = useContext(ChartSyncContext);
  if (!ctx) {
    // Fallback: use global store directly (charts used outside a provider)
    const store = useChartHoverStore.getState();
    return {
      syncId: 'global',
      hoverDistance: store.hoverDistance,
      hoverSource: store.hoverSource,
      setHover: store.setHover,
      clearHover: store.clearHover,
    };
  }
  return ctx;
}
