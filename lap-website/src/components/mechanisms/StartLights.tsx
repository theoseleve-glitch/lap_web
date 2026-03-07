'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { colors } from '@/lib/tokens';

interface StartLightsProps {
  onComplete: () => void;
  reducedMotion?: boolean;
}

const LIGHT_INTERVAL_MS = 1000;

export function StartLights({ onComplete, reducedMotion = false }: StartLightsProps) {
  const [litCount, setLitCount] = useState(0);
  const [lightsOut, setLightsOut] = useState(false);
  const completedRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countRef = useRef(0);

  // Reduced motion: skip straight to complete
  useEffect(() => {
    if (reducedMotion && !completedRef.current) {
      setLitCount(5);
      setLightsOut(true);
      completedRef.current = true;
      onComplete();
    }
  }, [onComplete, reducedMotion]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const startHold = useCallback(() => {
    if (completedRef.current || reducedMotion) return;

    // Reset if restarting
    countRef.current = 0;
    setLitCount(0);
    setLightsOut(false);

    // Light one immediately, then every second
    countRef.current = 1;
    setLitCount(1);

    intervalRef.current = setInterval(() => {
      countRef.current += 1;
      setLitCount(countRef.current);
      if (countRef.current >= 5) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }, LIGHT_INTERVAL_MS);
  }, [reducedMotion]);

  const endHold = useCallback(() => {
    if (completedRef.current || reducedMotion) return;

    // Stop the interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (countRef.current >= 5) {
      // All 5 lit — lights out! Scroll to next section.
      setLightsOut(true);
      completedRef.current = true;
      onComplete();
    } else {
      // Released early — reset
      countRef.current = 0;
      setLitCount(0);
    }
  }, [onComplete, reducedMotion]);

  return (
    <div
      className="flex items-center justify-center gap-5 md:gap-8 select-none py-10 cursor-pointer touch-none"
      role="group"
      aria-label="F1 start lights — press and hold to light all five, then release"
      onPointerDown={startHold}
      onPointerUp={endHold}
      onPointerLeave={endHold}
      onKeyDown={(e) => {
        if (e.repeat) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          startHold();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          endHold();
        }
      }}
      tabIndex={completedRef.current ? -1 : 0}
    >
      {Array.from({ length: 5 }).map((_, i) => {
        const lit = !lightsOut && i < litCount;
        return (
          <div
            key={i}
            className="w-14 h-14 md:w-20 md:h-20 rounded-full border-2 transition-all duration-300"
            style={{
              background: lit ? colors.safetyRed : 'rgba(255,42,42,0.08)',
              borderColor: lit ? colors.safetyRed : 'rgba(255,42,42,0.25)',
              boxShadow: lit
                ? `0 0 30px ${colors.safetyRed}, 0 0 60px ${colors.safetyRed}60, 0 0 100px ${colors.safetyRed}30, inset 0 0 20px rgba(255,255,255,0.15)`
                : `inset 0 0 15px rgba(255,42,42,0.06)`,
              opacity: lit ? 1 : 0.5,
            }}
          />
        );
      })}
    </div>
  );
}
