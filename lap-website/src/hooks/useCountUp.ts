'use client';

import { useEffect, useRef, useState } from 'react';

interface CountUpOptions {
  end: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  disabled?: boolean;
}

export function useCountUp(options: CountUpOptions) {
  const { end, duration = 2000, prefix = '', suffix = '', decimals = 0, disabled = false } = options;
  const ref = useRef<HTMLElement>(null);
  const [display, setDisplay] = useState(`${prefix}0${suffix}`);

  useEffect(() => {
    if (disabled || !ref.current) {
      setDisplay(`${prefix}${end.toFixed(decimals)}${suffix}`);
      return;
    }

    let triggered = false;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !triggered) {
          triggered = true;
          const start = performance.now();
          const animate = (now: number) => {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - (1 - progress) * (1 - progress);
            const current = eased * end;
            setDisplay(`${prefix}${current.toFixed(decimals)}${suffix}`);
            if (progress < 1) requestAnimationFrame(animate);
          };
          requestAnimationFrame(animate);
        }
      },
      { threshold: 0.5 },
    );

    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [end, duration, prefix, suffix, decimals, disabled]);

  return { ref, display };
}
