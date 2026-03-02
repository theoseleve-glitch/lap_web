'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { rooms, timing, easing } from '@/lib/tokens';

gsap.registerPlugin(ScrollTrigger);

export function MotionOrchestrator() {
  const prevChapterRef = useRef(0);
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  // DOM room enter/exit synchronized with WebGL transitions
  useEffect(() => {
    if (reducedMotion) return;

    const prevIdx = prevChapterRef.current;
    if (currentChapter === prevIdx) return;
    prevChapterRef.current = currentChapter;

    const prevRoom = rooms[prevIdx];
    const nextRoom = rooms[currentChapter];

    const prevEl = prevRoom ? document.getElementById(prevRoom.id) : null;
    const nextEl = nextRoom ? document.getElementById(nextRoom.id) : null;

    // Exit previous
    if (prevEl) {
      gsap.to(prevEl, {
        opacity: 0,
        filter: 'blur(6px)',
        y: -15,
        duration: timing.room * 0.6,
        ease: easing.snap,
      });
    }

    // Enter next
    if (nextEl) {
      gsap.fromTo(nextEl, {
        opacity: 0,
        filter: 'blur(6px)',
        y: 20,
      }, {
        opacity: 1,
        filter: 'blur(0px)',
        y: 0,
        duration: timing.room,
        ease: easing.inertia,
        delay: timing.room * 0.3,
      });
    }
  }, [currentChapter, reducedMotion]);

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
