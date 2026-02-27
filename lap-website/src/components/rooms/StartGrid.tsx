'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { StartLights } from '@/components/mechanisms/StartLights';
import { startGrid } from '@/data/copy';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { trackStartGridHold, trackStartGridComplete } from '@/lib/analytics';
import { getVariantForKey } from '@/lib/experiments';

export function StartGrid() {
  const [launched, setLaunched] = useState(false);
  const [flashing, setFlashing] = useState(false);
  const [heroVariant, setHeroVariant] = useState<'control' | 'performance_focus'>('control');
  const holdStartRef = useRef(0);
  const scrollIntentRef = useRef(0);
  const { reducedMotion } = useReducedMotion();
  useEffect(() => {
    const variant = getVariantForKey('hero', 'control');
    setHeroVariant(variant === 'performance_focus' ? 'performance_focus' : 'control');
  }, []);
  const monument =
    heroVariant === 'performance_focus'
      ? ['YOUR DATA', 'HAS A LAP-TIME EDGE']
      : startGrid.monument;

  const handleComplete = useCallback(async () => {
    if (launched) return;

    // Track hold duration
    if (holdStartRef.current > 0) {
      trackStartGridHold(Date.now() - holdStartRef.current);
    }
    trackStartGridComplete();

    // Flash
    setFlashing(true);
    await new Promise((r) => setTimeout(r, 120));
    setFlashing(false);
    setLaunched(true);

    // Scroll to S1 (Lenis intercepts native smooth scroll)
    const target = document.getElementById('s1-pain');
    if (target) {
      target.scrollIntoView({ behavior: 'smooth' });
    }
  }, [launched]);

  useEffect(() => {
    if (launched) return;

    const handleWheel = (event: WheelEvent) => {
      if (event.deltaY <= 0) return;
      scrollIntentRef.current += event.deltaY;
      if (scrollIntentRef.current >= 220) {
        void handleComplete();
      }
    };

    window.addEventListener('wheel', handleWheel, { passive: true });
    return () => window.removeEventListener('wheel', handleWheel);
  }, [handleComplete, launched]);

  return (
    <section
      id="start-grid"
      data-accent="none"
      className="room relative"
      aria-label="Start Grid"
      onPointerDown={() => { holdStartRef.current = Date.now(); }}
    >
      {/* White flash overlay */}
      {flashing && (
        <div className="absolute inset-0 bg-chalk z-50 pointer-events-none" />
      )}

      <div className="grid-lap">
        <div className="col-span-full flex flex-col items-center justify-center text-center gap-8 md:gap-12">
          <MonumentText size="xl" as="h1" className="text-center">
            {monument[0]}<br />{monument[1]}
          </MonumentText>

          {!launched && (
            <>
              <StartLights
                onComplete={handleComplete}
                reducedMotion={reducedMotion}
              />
              <p className="font-telemetry text-steel">
                {startGrid.instruction} {/* OR SCROLL TO LAUNCH */}
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
