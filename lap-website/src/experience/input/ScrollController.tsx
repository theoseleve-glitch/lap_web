'use client';

import { useEffect, useRef } from 'react';
import Lenis from 'lenis';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';
import { physics } from '@/experience/motion/springs';

gsap.registerPlugin(ScrollTrigger);

export function ScrollController() {
  const lenisRef = useRef<Lenis | null>(null);
  const velocityRef = useRef(0);
  const setScrollY = useKernelStore((s) => s.setScrollY);
  const setScrollVelocity = useKernelStore((s) => s.setScrollVelocity);
  const setScrollDirection = useKernelStore((s) => s.setScrollDirection);
  const setGlobalProgress = useKernelStore((s) => s.setGlobalProgress);
  const setCurrentChapter = useKernelStore((s) => s.setCurrentChapter);
  const setChapterProgress = useKernelStore((s) => s.setChapterProgress);
  const setMode = useKernelStore((s) => s.setMode);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  useEffect(() => {
    const lenis = new Lenis({
      lerp: reducedMotion ? 0.9 : physics.scrollLerp,
      duration: physics.scrollDuration,
      smoothWheel: true,
      touchMultiplier: 1.5,
    });

    lenisRef.current = lenis;

    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((time) => lenis.raf(time * 1000));
    gsap.ticker.lagSmoothing(0);

    lenis.on('scroll', ({ scroll, velocity, direction }: {
      scroll: number;
      velocity: number;
      direction: number;
    }) => {
      setScrollY(scroll);

      const normalized = Math.max(-1, Math.min(1, velocity / 1000));
      velocityRef.current += (normalized - velocityRef.current) * physics.velocitySmoothing;
      setScrollVelocity(velocityRef.current);

      setScrollDirection(direction > 0 ? 'down' : direction < 0 ? 'up' : 'idle');

      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      if (docHeight > 0) {
        setGlobalProgress(scroll / docHeight);
      }
    });

    rooms.forEach((room, index) => {
      ScrollTrigger.create({
        trigger: `#${room.id}`,
        start: 'top center',
        end: 'bottom center',
        onEnter: () => setCurrentChapter(index),
        onEnterBack: () => setCurrentChapter(index),
        onUpdate: (self) => setChapterProgress(self.progress),
      });
    });

    let idleTimer: ReturnType<typeof setTimeout>;
    lenis.on('scroll', () => {
      const currentMode = useKernelStore.getState().mode;
      if (currentMode === 'preloading' || currentMode === 'transitioning') return;

      setMode('scrolling');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (useKernelStore.getState().mode === 'scrolling') {
          setMode('idle');
        }
      }, 150);
    });

    return () => {
      lenis.destroy();
      ScrollTrigger.getAll().forEach((st) => st.kill());
      clearTimeout(idleTimer);
    };
  }, [
    reducedMotion, setScrollY, setScrollVelocity, setScrollDirection,
    setGlobalProgress, setCurrentChapter, setChapterProgress, setMode,
  ]);

  return null;
}
