'use client';

import { useEffect, useRef, useState } from 'react';
import gsap from 'gsap';
import { useKernelStore } from '@/experience/state/store';
import { timing } from '@/lib/tokens';

export function FinishLine() {
  const crossed = useKernelStore((s) => s.finish.crossed);
  const bandRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const hasAnimated = useRef(false);
  const tweensRef = useRef<gsap.core.Tween[]>([]);

  useEffect(() => {
    if (!crossed || hasAnimated.current || !bandRef.current) return;
    hasAnimated.current = true;

    setVisible(true);
    const el = bandRef.current;

    // Sweep from left to right
    const sweep = gsap.fromTo(
      el,
      { x: '-100%', opacity: 1 },
      {
        x: '100%',
        duration: timing.finish,
        ease: 'power2.inOut',
        onComplete: () => {
          // Hold briefly then fade
          const fade = gsap.to(el, {
            opacity: 0,
            duration: 0.4,
            delay: 0.6,
            onComplete: () => setVisible(false),
          });
          tweensRef.current.push(fade);
        },
      },
    );
    tweensRef.current.push(sweep);
  }, [crossed]);

  // Cleanup GSAP tweens on unmount
  useEffect(() => {
    return () => { tweensRef.current.forEach((t) => t.kill()); };
  }, []);

  if (!visible && !crossed) return null;

  return (
    <div
      className="fixed inset-x-0 top-1/2 -translate-y-1/2 pointer-events-none overflow-hidden"
      style={{
        height: '48px',
        zIndex: 'var(--z-finish-line)' as unknown as number,
      }}
      aria-hidden="true"
    >
      <div
        ref={bandRef}
        className="w-full h-full"
        style={{
          opacity: 0,
          background: `repeating-conic-gradient(#000 0% 25%, #fff 0% 50%) 0 0 / 12px 12px`,
        }}
      />
    </div>
  );
}
