'use client';

import { type ReactNode, useState, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import { ExperienceKernel } from './ExperienceKernel';
import { ExperienceCanvas } from './renderer/ExperienceCanvas';
import { Preloader } from './preloader/Preloader';
import { FallbackShell } from './quality/FallbackShell';
import { useKernelStore } from './state/store';
import { useChapter } from './hooks/useChapter';
import { CustomCursor } from '@/components/chrome/CustomCursor';
import { DeltaStrip } from '@/components/chrome/DeltaStrip';
import { SectorTabs } from '@/components/chrome/SectorTabs';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { IndexOverlay } from '@/components/chrome/IndexOverlay';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { PerformanceProvider } from '@/lib/performance-context';

function ExperienceContent({ children }: { children: ReactNode }) {
  const [overlayOpen, setOverlayOpen] = useState(false);
  const { id: activeRoom } = useChapter();
  const webglAvailable = useKernelStore((s) => s.webglAvailable);

  const toggleOverlay = useCallback(() => setOverlayOpen((prev) => !prev), []);
  const closeOverlay = useCallback(() => setOverlayOpen(false), []);

  const content = (
    <>
      <SiteHeader showIndexToggle onIndexToggle={toggleOverlay} />
      <CustomCursor />
      <TimecodeCounter />
      <SectorTabs />
      <DeltaStrip />
      <IndexOverlay isOpen={overlayOpen} onClose={closeOverlay} fromSection={activeRoom} />

      {/* Layer 1: WebGL */}
      {webglAvailable && <ExperienceCanvas />}

      {/* Layer 2: DOM content */}
      <div className="relative z-10">
        {children}
      </div>

      <SiteFooter />
    </>
  );

  return webglAvailable ? content : <FallbackShell>{content}</FallbackShell>;
}

function HomepageShell({ children }: { children: ReactNode }) {
  return (
    <ExperienceKernel>
      <Preloader />
      <ExperienceContent>{children}</ExperienceContent>
    </ExperienceKernel>
  );
}

function SubpageShell({ children }: { children: ReactNode }) {
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

export function ExperienceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isHome = pathname === '/';

  if (!isHome) {
    return <SubpageShell>{children}</SubpageShell>;
  }

  return <HomepageShell>{children}</HomepageShell>;
}
