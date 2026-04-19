'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { gsap } from 'gsap';

interface PreloaderProps {
  onComplete: () => void;
}

export function Preloader({ onComplete }: PreloaderProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const countRef = useRef<HTMLSpanElement>(null);
  const [count, setCount] = useState(5);

  const stableOnComplete = useCallback(onComplete, [onComplete]);

  useEffect(() => {
    if (sessionStorage.getItem('lap_preloader_seen')) {
      stableOnComplete();
      return;
    }

    const steps = [5, 4, 3, 2, 1];
    let i = 0;
    let cancelled = false;

    const tick = () => {
      if (cancelled) return;

      if (i < steps.length) {
        setCount(steps[i]);
        if (countRef.current) {
          gsap.fromTo(countRef.current, {
            scale: 1.3,
            opacity: 0,
          }, {
            scale: 1,
            opacity: 1,
            duration: 0.3,
            ease: 'power2.out',
          });
        }
        i++;
        setTimeout(tick, 400);
      } else {
        // "GO" reveal
        setCount(0);
        if (countRef.current) {
          gsap.fromTo(countRef.current, {
            scale: 0.5,
            opacity: 0,
          }, {
            scale: 1.2,
            opacity: 1,
            duration: 0.3,
            ease: 'power3.out',
          });
        }

        setTimeout(() => {
          if (cancelled) return;
          if (containerRef.current) {
            gsap.to(containerRef.current, {
              opacity: 0,
              scale: 1.05,
              filter: 'blur(20px)',
              duration: 0.6,
              ease: 'power2.inOut',
              onComplete: () => {
                sessionStorage.setItem('lap_preloader_seen', '1');
                stableOnComplete();
              },
            });
          }
        }, 500);
      }
    };

    setTimeout(tick, 200);

    return () => { cancelled = true; };
  }, [stableOnComplete]);

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[1000] bg-asphalt flex flex-col items-center justify-center"
    >
      {/* Horizontal accent lines */}
      <div className="absolute top-1/2 left-0 w-full h-px bg-gold/10" />
      <div className="absolute top-[calc(50%-40px)] left-0 w-full h-px bg-steel/5" />
      <div className="absolute top-[calc(50%+40px)] left-0 w-full h-px bg-steel/5" />

      <span
        ref={countRef}
        className="font-monument text-gold"
        style={{ fontSize: 'clamp(80px, 20vw, 200px)', lineHeight: 1 }}
      >
        {count === 0 ? 'GO' : count}
      </span>

      <span className="font-telemetry text-[10px] tracking-[0.2em] uppercase text-steel/40 mt-8">
        INITIALIZING LAP ANALYSIS ENGINE
      </span>
    </div>
  );
}
