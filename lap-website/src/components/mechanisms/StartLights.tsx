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
      className="flex items-center justify-center gap-4 md:gap-6 select-none touch-none cursor-pointer py-8"
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
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="w-12 h-12 md:w-16 md:h-16 rounded-full transition-all duration-300"
          style={{
            background: i < litCount ? colors.safetyRed : colors.concrete,
            boxShadow: i < litCount ? `0 0 30px ${colors.safetyRed}, 0 0 60px ${colors.safetyRed}40` : 'none',
            opacity: i < litCount ? 1 : 0.3,
          }}
        />
      ))}
    </div>
  );
}
