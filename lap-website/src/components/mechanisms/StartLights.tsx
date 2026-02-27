'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { colors } from '@/lib/tokens';

interface StartLightsProps {
  onComplete: () => void;
  reducedMotion?: boolean;
}

export function StartLights({ onComplete, reducedMotion = false }: StartLightsProps) {
  const [litCount, setLitCount] = useState(0);
  const [holding, setHolding] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval>>();
  const completedRef = useRef(false);

  const startHold = useCallback(() => {
    if (completedRef.current) return;

    if (reducedMotion) {
      setLitCount(5);
      completedRef.current = true;
      onComplete();
      return;
    }

    setHolding(true);
    setLitCount(0);
    let count = 0;

    intervalRef.current = setInterval(() => {
      count++;
      setLitCount(count);
      if (count >= 5) {
        clearInterval(intervalRef.current);
      }
    }, 400);
  }, [onComplete, reducedMotion]);

  const endHold = useCallback(() => {
    if (!holding || completedRef.current) return;
    setHolding(false);
    clearInterval(intervalRef.current);

    if (litCount >= 5) {
      completedRef.current = true;
      onComplete();
    } else {
      setLitCount(0);
    }
  }, [holding, litCount, onComplete]);

  // Cleanup
  useEffect(() => {
    return () => clearInterval(intervalRef.current);
  }, []);

  return (
    <div
      className="flex items-center justify-center gap-5 md:gap-8 select-none touch-none cursor-pointer py-10"
      onPointerDown={startHold}
      onPointerUp={endHold}
      onPointerLeave={endHold}
      onKeyDown={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          startHold();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === ' ' || e.key === 'Enter') {
          endHold();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label="Hold to start — press and hold for 2 seconds"
    >
      {Array.from({ length: 5 }).map((_, i) => {
        const lit = i < litCount;
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
