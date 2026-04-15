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
import { GrainOverlay } from '@/components/chrome/GrainOverlay';
import { AmbientGlow } from '@/components/chrome/AmbientGlow';
import { CustomScrollbar } from '@/components/chrome/CustomScrollbar';
import { SoundToggle } from '@/components/chrome/SoundToggle';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { PerformanceProvider } from '@/lib/performance-context';
import { EXPERIENCE_V2 } from '@/lib/feature-flags';
import { soundManager } from '@/lib/sound-manager';
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
      <GrainOverlay />
      <AmbientGlow />
      <CustomScrollbar />
      <SoundToggle />
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
  // Lenis smooth scroll is handled by ExperienceKernel → InputManager → ScrollController.
  // That instance also feeds globalProgress/scrollVelocity/currentChapter into the kernel
  // store, which drives the 3D background (TrackRibbon, SpeedStreaks, BackgroundController).
  // Do NOT add a second useLenis here — two Lenis instances will fight each other.

  useEffect(() => {
    window.scrollTo(0, 0);
    soundManager.init();
    soundManager.startAmbient();
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
        <GrainOverlay />
        <AmbientGlow />
        <CustomScrollbar />
        <CustomCursor />
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
