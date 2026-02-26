'use client';

import { useState, useCallback, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
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
        <SiteHeader showIndexToggle onIndexToggle={toggleOverlay} />
        <CustomCursor />
        <TimecodeCounter />
        <SectorTabs />
        <DeltaStrip />
        <IndexOverlay isOpen={overlayOpen} onClose={closeOverlay} fromSection={activeRoom} />
        {children}
        <SiteFooter />
      </GsapProvider>
    </PerformanceProvider>
  );
}
