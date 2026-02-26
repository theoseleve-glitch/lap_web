'use client';

import { useState, useRef, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { StartLights } from '@/components/mechanisms/StartLights';
import { startGrid } from '@/data/copy';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { trackStartGridHold, trackStartGridComplete } from '@/lib/analytics';

export function StartGrid() {
  const [launched, setLaunched] = useState(false);
  const [flashing, setFlashing] = useState(false);
  const holdStartRef = useRef(0);
  const { reducedMotion } = useReducedMotion();

  const handleComplete = useCallback(async () => {
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

    // Scroll to S1
    const { gsap } = await import('gsap');
    const { ScrollToPlugin } = await import('gsap/ScrollToPlugin');
    gsap.registerPlugin(ScrollToPlugin);
    gsap.to(window, {
      scrollTo: '#s1-pain',
      duration: 0.9,
      ease: 'power3.out',
    });
  }, []);

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
            {startGrid.monument[0]}<br />{startGrid.monument[1]}
          </MonumentText>

          {!launched && (
            <>
              <StartLights
                onComplete={handleComplete}
                reducedMotion={reducedMotion}
              />
              <p className="font-telemetry text-steel">
                {startGrid.instruction}
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
