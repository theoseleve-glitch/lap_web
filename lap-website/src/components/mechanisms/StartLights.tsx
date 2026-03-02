'use client';

import { useState, useRef, useEffect } from 'react';
import { colors } from '@/lib/tokens';

interface StartLightsProps {
  onComplete: () => void;
  reducedMotion?: boolean;
}

export function StartLights({ onComplete, reducedMotion = false }: StartLightsProps) {
  const [litCount, setLitCount] = useState(0);
  const [lightsOut, setLightsOut] = useState(false);
  const completedRef = useRef(false);

  // Auto-play: light up 1→5 sequentially, then "lights out" → green flag
  useEffect(() => {
    if (completedRef.current) return;

    if (reducedMotion) {
      setLitCount(5);
      setLightsOut(true);
      completedRef.current = true;
      onComplete();
      return;
    }

    let count = 0;
    const interval = setInterval(() => {
      count++;
      setLitCount(count);
      if (count >= 5) {
        clearInterval(interval);
        // Hold all 5 lit for 800ms, then lights out
        setTimeout(() => {
          setLightsOut(true);
          completedRef.current = true;
          onComplete();
        }, 800);
      }
    }, 400);

    return () => clearInterval(interval);
  }, [onComplete, reducedMotion]);

  return (
    <div
      className="flex items-center justify-center gap-5 md:gap-8 select-none py-10"
      aria-label="F1 start lights sequence"
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
