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
        clipPath: 'inset(0 100% 0 0)',
      }, {
        clipPath: 'inset(0 0% 0 0)',
        duration: timing.monument,
        ease: easing.inertia,
        scrollTrigger: {
          trigger: el,
          start: 'top 80%',
          toggleActions: 'play none none none',
        },
      });
    });

    return () => ScrollTrigger.getAll().forEach((st) => st.kill());
  }, [reducedMotion]);

  return null;
}
