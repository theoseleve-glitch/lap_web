'use client';

import { useState, useEffect, useCallback } from 'react';
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
import { VenueHome } from '@/components/rooms/VenueHome';

const MARQUEE_TOP = [
  'TELEMETRY', 'LAP ANALYSIS', 'CORNER COACHING', 'RACE STRATEGY',
  'PIT PLANNING', 'DATA ENGINEERING', 'PERFORMANCE SCORING',
];

const MARQUEE_MID = [
  'PACE', 'CONSISTENCY', 'EXECUTION', 'ROBUSTNESS',
  'BRAKING', 'APEX SPEED', 'EXIT DRIVE', 'RACING LINE',
];

type Persona = 'chooser' | 'drivers' | 'venues';

function getPersonaCookie(): Persona {
  if (typeof document === 'undefined') return 'chooser';
  const match = document.cookie
    .split(';')
    .map((c) => c.trim())
    .find((c) => c.startsWith('lap_persona='));
  if (!match) return 'chooser';
  const val = match.split('=').slice(1).join('=');
  if (val === 'drivers') return 'drivers';
  if (val === 'venues' || val === 'circuits' || val === 'teams') return 'venues';
  return 'chooser';
}

function clearPersonaCookie() {
  document.cookie = 'lap_persona=;path=/;max-age=0;SameSite=Lax';
}

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
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel/40 hover:text-steel transition-colors"
          onClick={onSwitch}
        >
          Not a driver? Switch to venue view
        </button>
      </div>
    </main>
  );
}

/* ── Venue Homepage wrapper (adds switch link) ── */
function VenueHomeWithSwitch({ onSwitch }: { onSwitch: () => void }) {
  return (
    <>
      <VenueHome />

      {/* Switch link */}
      <div className="flex justify-center pb-8">
        <button
          className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel/40 hover:text-steel transition-colors"
          onClick={onSwitch}
        >
          Are you a driver? Switch to driver view
        </button>
      </div>
    </>
  );
}

/* ── Page orchestrator ────────────────────────── */
export default function Home() {
  const [persona, setPersona] = useState<Persona>('chooser');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setPersona(getPersonaCookie());
    setMounted(true);
  }, []);

  const handleChoose = useCallback((chosen: string) => {
    const p: Persona = chosen === 'drivers' ? 'drivers' : 'venues';
    setPersona(p);
  }, []);

  const handleSwitch = useCallback(() => {
    clearPersonaCookie();
    setPersona('chooser');
    window.scrollTo({ top: 0 });
  }, []);

  // Before hydration, render nothing to avoid flash
  if (!mounted) return null;

  if (persona === 'chooser') {
    return <AudienceChooser onChoose={handleChoose} />;
  }

  if (persona === 'venues') {
    return <VenueHomeWithSwitch onSwitch={handleSwitch} />;
  }

  return <DriverHome onSwitch={handleSwitch} />;
}
