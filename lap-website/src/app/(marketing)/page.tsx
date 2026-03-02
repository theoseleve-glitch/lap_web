'use client';

import { useState, useCallback } from 'react';
import { StartGrid } from '@/components/rooms/StartGrid';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S1DeepSculpture } from '@/components/rooms/S1DeepSculpture';
import { S2Pipeline } from '@/components/rooms/S2Pipeline';
import { S2Versus } from '@/components/rooms/S2Versus';
import { S3Product } from '@/components/rooms/S3Product';
import { S4WorkflowCoverage } from '@/components/rooms/S4WorkflowCoverage';
import { PitStop } from '@/components/rooms/PitStop';
import { Garage } from '@/components/rooms/Garage';
import { Podium } from '@/components/rooms/Podium';
import { MarqueeStrip } from '@/components/ui/MarqueeStrip';
import { AudienceChooser } from '@/components/rooms/AudienceChooser';

const MARQUEE_TOP = [
  'TELEMETRY', 'LAP ANALYSIS', 'CORNER COACHING', 'RACE STRATEGY',
  'PIT PLANNING', 'DATA ENGINEERING', 'PERFORMANCE SCORING',
];

const MARQUEE_MID = [
  'PACE', 'CONSISTENCY', 'EXECUTION', 'ROBUSTNESS',
  'BRAKING', 'APEX SPEED', 'EXIT DRIVE', 'RACING LINE',
];

/* ── Driver Homepage ──────────────────────────── */
function DriverHome({ onSwitch }: { onSwitch: () => void }) {
  return (
    <main id="main-content">
      <StartGrid />
      <S1Pain />
      <MarqueeStrip items={MARQUEE_TOP} speed={35} />
      <S1DeepSculpture />
      <S2Pipeline />
      <S2Versus />
      <S3Product />
      <S4WorkflowCoverage />
      <MarqueeStrip items={MARQUEE_MID} speed={40} reverse />
      <div id="s5-personas" aria-hidden="true" />
      <PitStop />
      <Garage />
      <Podium />

      {/* Switch link */}
      <div className="flex justify-center pb-8">
        <button
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel/60 hover:text-steel transition-colors"
          onClick={onSwitch}
        >
          Not a driver? Switch to venue view
        </button>
      </div>
    </main>
  );
}

/* ── Page orchestrator ────────────────────────── */
export default function Home() {
  // Always start with the chooser — no cookie bypass
  const [showDriverHome, setShowDriverHome] = useState(false);

  const handleChoose = useCallback((chosen: string) => {
    if (chosen === 'drivers') setShowDriverHome(true);
    // 'venues' navigates to /contact via AudienceChooser directly
  }, []);

  const handleSwitch = useCallback(() => {
    setShowDriverHome(false);
    window.scrollTo({ top: 0 });
  }, []);

  if (!showDriverHome) {
    return <AudienceChooser onChoose={handleChoose} />;
  }

  return <DriverHome onSwitch={handleSwitch} />;
}
