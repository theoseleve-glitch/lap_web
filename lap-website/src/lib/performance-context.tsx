'use client';

import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { useFpsMonitor } from '@/hooks/useFpsMonitor';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface PerformanceState {
  isLowPerf: boolean;
  isReducedMotion: boolean;
  isMobile: boolean;
  isBatterySaver: boolean;
}

const PerformanceContext = createContext<PerformanceState>({
  isLowPerf: false,
  isReducedMotion: false,
  isMobile: false,
  isBatterySaver: false,
});

export function usePerformance() {
  return useContext(PerformanceContext);
}

export function PerformanceProvider({ children }: { children: ReactNode }) {
  const { isLowFps } = useFpsMonitor(40);
  const { reducedMotion } = useReducedMotion();
  const [isMobile, setIsMobile] = useState(false);
  const [isBatterySaver, setIsBatterySaver] = useState(false);

  useEffect(() => {
    setIsMobile(window.matchMedia('(max-width: 767px)').matches);

    const mq = window.matchMedia('(max-width: 767px)');
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener('change', handler);

    // Battery API (non-standard, available in Chromium browsers)
    interface BatteryManager extends EventTarget {
      charging: boolean;
      level: number;
    }
    type NavigatorWithBattery = Navigator & {
      getBattery?: () => Promise<BatteryManager>;
    };

    const nav = navigator as NavigatorWithBattery;
    if (nav.getBattery) {
      nav.getBattery().then((battery: BatteryManager) => {
        const check = () => {
          if (battery.level < 0.2 && !battery.charging) {
            setIsBatterySaver(true);
          }
        };
        check();
        battery.addEventListener('levelchange', check);
        battery.addEventListener('chargingchange', check);
      }).catch(() => {});
    }

    return () => mq.removeEventListener('change', handler);
  }, []);

  const value: PerformanceState = {
    isLowPerf: isLowFps || isBatterySaver,
    isReducedMotion: reducedMotion,
    isMobile,
    isBatterySaver,
  };

  return (
    <PerformanceContext.Provider value={value}>
      {children}
    </PerformanceContext.Provider>
  );
}
