'use client';

import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { LapWordmark } from '@/components/chrome/LapWordmark';
import { IndexOverlay } from '@/components/chrome/IndexOverlay';
import { CustomCursor } from '@/components/chrome/CustomCursor';
import { PerformanceProvider } from '@/lib/performance-context';
import { useActiveRoom } from '@/hooks/useActiveRoom';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';

export function ChromeLayout({ children }: { children: ReactNode }) {
  const [overlayOpen, setOverlayOpen] = useState(false);
  const activeRoom = useActiveRoom();
  const pathname = usePathname();
  const isHome = pathname === '/';

  // I key to toggle overlay
  useEffect(() => {
    if (!isHome) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'i' || e.key === 'I') {
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          setOverlayOpen((prev) => !prev);
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isHome]);

  const toggleOverlay = useCallback(() => setOverlayOpen((prev) => !prev), []);
  const closeOverlay = useCallback(() => setOverlayOpen(false), []);

  if (!isHome) {
    return (
      <PerformanceProvider>
        <GsapProvider>
          <SiteHeader />
          {children}
          <SiteFooter />
        </GsapProvider>
      </PerformanceProvider>
    );
  }

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
