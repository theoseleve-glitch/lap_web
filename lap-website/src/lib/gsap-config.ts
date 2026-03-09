'use client';

import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

let registered = false;

export function registerGsap() {
  if (registered) return;
  gsap.registerPlugin(ScrollTrigger);

  // Respect prefers-reduced-motion: disable all GSAP animations globally.
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (mq.matches) {
    gsap.globalTimeline.timeScale(0);
    ScrollTrigger.defaults({ animation: undefined });
    gsap.defaults({ duration: 0 });
  }
  mq.addEventListener('change', (e) => {
    if (e.matches) {
      gsap.globalTimeline.timeScale(0);
      gsap.defaults({ duration: 0 });
    } else {
      gsap.globalTimeline.timeScale(1);
      gsap.defaults({ duration: 0.5 });
    }
  });

  registered = true;
}
