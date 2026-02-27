import { gsap } from 'gsap';
import { timing, easing } from '@/lib/tokens';

export type TimelineType = 'enter' | 'exit' | 'scrub';

interface TimelineOptions {
  target: Element | string;
  type: TimelineType;
  delay?: number;
  onComplete?: () => void;
}

export function createRoomTimeline({ target, type, delay = 0, onComplete }: TimelineOptions) {
  const tl = gsap.timeline({ delay, onComplete });

  switch (type) {
    case 'enter':
      tl.fromTo(target, {
        opacity: 0,
        y: 30,
        filter: 'blur(8px)',
      }, {
        opacity: 1,
        y: 0,
        filter: 'blur(0px)',
        duration: timing.room,
        ease: easing.inertia,
      });
      break;

    case 'exit':
      tl.to(target, {
        opacity: 0,
        y: -20,
        filter: 'blur(8px)',
        duration: timing.room,
        ease: easing.snap,
      });
      break;

    case 'scrub':
      // Returns a timeline meant to be scrubbed via ScrollTrigger
      tl.fromTo(target, {
        opacity: 0.3,
        y: 40,
      }, {
        opacity: 1,
        y: 0,
        duration: 1, // Normalized for scrub
        ease: 'none',
      });
      break;
  }

  return tl;
}
