'use client';

import { useEffect } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { timing } from '@/lib/tokens';

gsap.registerPlugin(ScrollTrigger);

export function MotionOrchestrator() {
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  // MonumentText reveal via ScrollTrigger (replaces per-component GSAP)
  useEffect(() => {
    if (reducedMotion) return;

    const monuments = document.querySelectorAll('[data-monument-reveal]');
    monuments.forEach((el) => {
      gsap.fromTo(el, {
        opacity: 0,
        y: 40,
        filter: 'blur(10px)',
      }, {
        opacity: 1,
        y: 0,
        filter: 'blur(0px)',
        duration: timing.monument * 1.2,
        ease: 'power3.out',
        scrollTrigger: {
          trigger: el,
          start: 'top 85%',
          toggleActions: 'play none none none',
        },
      });
    });

    // Staggered grid card reveals — Apple-style cascade
    const grids = document.querySelectorAll('.room .grid');
    grids.forEach((grid) => {
      const cards = grid.querySelectorAll('.beam-card, [class*="border-chalk"]');
      if (cards.length < 2) return;

      gsap.fromTo(cards, {
        opacity: 0,
        y: 30,
      }, {
        opacity: 1,
        y: 0,
        duration: 0.6,
        ease: 'power2.out',
        stagger: 0.1,
        scrollTrigger: {
          trigger: grid,
          start: 'top 80%',
          toggleActions: 'play none none none',
        },
      });
    });

    return () => ScrollTrigger.getAll().forEach((st) => st.kill());
  }, [reducedMotion]);

  return null;
}
