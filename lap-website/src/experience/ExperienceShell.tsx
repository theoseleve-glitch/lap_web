'use client';

import { type ReactNode, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { ExperienceKernel } from './ExperienceKernel';

import { FallbackShell } from './quality/FallbackShell';
import { useKernelStore } from './state/store';
import { CustomCursor } from '@/components/chrome/CustomCursor';
import { TimingTower } from '@/components/chrome/TimingTower';
import { DeltaHud } from '@/components/chrome/DeltaHud';
import { MiniTrackMap } from '@/components/chrome/MiniTrackMap';
import { DrsLabel } from '@/components/chrome/DrsLabel';
import { SectorGateSweep } from '@/components/chrome/SectorGateSweep';
import { FinishLine } from '@/components/chrome/FinishLine';
import { TimecodeCounter } from '@/components/chrome/TimecodeCounter';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { PerformanceProvider } from '@/lib/performance-context';
import { EXPERIENCE_V2 } from '@/lib/feature-flags';
import dynamic from 'next/dynamic';

const BackgroundCanvas = dynamic(
  () => import('./background/BackgroundCanvas').then((m) => m.BackgroundCanvas),
  { ssr: false },
);

function ExperienceContent({ children }: { children: ReactNode }) {
  const webglAvailable = useKernelStore((s) => s.webglAvailable);

  const content = (
    <>
      <SiteHeader />
      <CustomCursor />
      <TimecodeCounter />
      {EXPERIENCE_V2 && <TimingTower />}
      {EXPERIENCE_V2 && <DeltaHud />}
      {EXPERIENCE_V2 && <MiniTrackMap />}
      {EXPERIENCE_V2 && <DrsLabel />}
      {EXPERIENCE_V2 && <SectorGateSweep />}
      {EXPERIENCE_V2 && <FinishLine />}

      {/* WebGL background layer — behind all content, driven by scroll */}
      {webglAvailable && <BackgroundCanvas />}

      {/* DOM content */}
      <div className="relative z-10">
        {children}
      </div>

      <SiteFooter />
    </>
  );

  return webglAvailable ? content : <FallbackShell>{content}</FallbackShell>;
}

function HomepageShell({ children }: { children: ReactNode }) {
  // Reset scroll after the full experience shell mounts —
  // prevents browser scroll restoration from hiding the hero.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  return (
    <ExperienceKernel>
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
