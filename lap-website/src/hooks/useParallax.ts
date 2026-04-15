'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

interface ParallaxOptions {
  speed?: number;
  direction?: 'vertical' | 'horizontal';
  disabled?: boolean;
}

export function useParallax<T extends HTMLElement>(options: ParallaxOptions = {}) {
  const ref = useRef<T>(null);
  const { speed = 0.8, direction = 'vertical', disabled = false } = options;

  useEffect(() => {
    if (disabled || !ref.current) return;

    const offset = (1 - speed) * 100;
    const prop = direction === 'vertical' ? 'y' : 'x';

    const st = ScrollTrigger.create({
      trigger: ref.current,
      start: 'top bottom',
      end: 'bottom top',
      scrub: 1.5,
      animation: gsap.fromTo(ref.current, {
        [prop]: -offset,
      }, {
        [prop]: offset,
        ease: 'none',
      }),
    });

    return () => st.kill();
  }, [speed, direction, disabled]);

  return ref;
}
