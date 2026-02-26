'use client';

import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { LapWordmark } from '@/components/chrome/LapWordmark';
import { IndexOverlay } from '@/components/chrome/IndexOverlay';
import { CustomCursor } from '@/components/chrome/CustomCursor';
import { PerformanceProvider } from '@/lib/performance-context';
import { useActiveRoom } from '@/hooks/useActiveRoom';

export function ChromeLayout({ children }: { children: ReactNode }) {
  const [overlayOpen, setOverlayOpen] = useState(false);
  const activeRoom = useActiveRoom();

  // I key to toggle overlay
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'i' || e.key === 'I') {
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          setOverlayOpen((prev) => !prev);
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  const toggleOverlay = useCallback(() => setOverlayOpen((prev) => !prev), []);
  const closeOverlay = useCallback(() => setOverlayOpen(false), []);

  return (
    <PerformanceProvider>
      <GsapProvider>
        <CustomCursor />
        <LapWordmark onIndexToggle={toggleOverlay} />
        <TimecodeCounter />
        <SectorTabs />
        <DeltaStrip />
        <IndexOverlay isOpen={overlayOpen} onClose={closeOverlay} fromSection={activeRoom} />
        {children}
      </GsapProvider>
    </PerformanceProvider>
  );
}
