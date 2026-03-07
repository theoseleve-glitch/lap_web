'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { colors } from '@/lib/tokens';

interface StartLightsProps {
  onComplete: () => void;
  reducedMotion?: boolean;
}

export function StartLights({ onComplete, reducedMotion = false }: StartLightsProps) {
  const [litCount, setLitCount] = useState(0);
  const [lightsOut, setLightsOut] = useState(false);
  const completedRef = useRef(false);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reduced motion: skip straight to complete
  useEffect(() => {
    if (reducedMotion && !completedRef.current) {
      setLitCount(5);
      setLightsOut(true);
      completedRef.current = true;
      onComplete();
    }
  }, [onComplete, reducedMotion]);

  // Clean up hold timer on unmount
  useEffect(() => {
    return () => {
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    };
  }, []);

  const advance = useCallback(() => {
    if (completedRef.current || reducedMotion) return;

    setLitCount((prev) => {
      const next = prev + 1;
      if (next >= 5) {
        // All 5 lit — hold then lights out
        holdTimerRef.current = setTimeout(() => {
          setLightsOut(true);
          completedRef.current = true;
          onComplete();
        }, 800);
      }
      return Math.min(next, 5);
    });
  }, [onComplete, reducedMotion]);

  return (
    <div
      className="flex items-center justify-center gap-5 md:gap-8 select-none py-10 cursor-pointer"
      role="group"
      aria-label="F1 start lights — tap to light each one"
      onClick={advance}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          advance();
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
