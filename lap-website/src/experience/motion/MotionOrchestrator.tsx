'use client';

import { useEffect } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useKernelStore } from '@/experience/state/store';
import { timing } from '@/lib/tokens';

gsap.registerPlugin(ScrollTrigger);

export function MotionOrchestrator() {
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  useEffect(() => {
    if (reducedMotion) return;

    // MonumentText reveal (non-split headlines — uses data-monument-reveal)
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

    // Enhanced section entrance: spatial movement + scale + blur + stagger
    const sections = document.querySelectorAll('section[data-accent]');
    sections.forEach((section) => {
      // Skip hero and pinned sections (they handle their own animation)
      if (section.id === 'start-grid' || section.id === 's3-product') return;

      const staggerTargets = section.querySelectorAll(
        '[data-stagger], .border:not(header .border)'
      );
      if (staggerTargets.length === 0) return;

      gsap.fromTo(staggerTargets, {
        opacity: 0,
        y: 50,
        scale: 0.97,
        filter: 'blur(4px)',
      }, {
        opacity: 1,
        y: 0,
        scale: 1,
        filter: 'blur(0px)',
        duration: 0.7,
        ease: 'power3.out',
        stagger: 0.1,
        scrollTrigger: {
          trigger: section,
          start: 'top 75%',
          toggleActions: 'play none none none',
        },
      });
    });

    // Velocity-based skewing on [data-skew] elements
    const skewTargets = document.querySelectorAll('[data-skew]');
    let lastScrollY = 0;
    let currentSkew = 0;
    let skewTickerActive = false;

    if (skewTargets.length > 0) {
      skewTickerActive = true;
      const updateSkew = () => {
        const velocity = window.scrollY - lastScrollY;
        lastScrollY = window.scrollY;

        const targetSkew = Math.max(-2, Math.min(2, velocity * 0.05));
        currentSkew += (targetSkew - currentSkew) * 0.1;

        skewTargets.forEach((el) => {
          (el as HTMLElement).style.transform = `skewY(${currentSkew.toFixed(3)}deg)`;
        });
      };

      gsap.ticker.add(updateSkew);
    }

    // Background color tinting based on active section
    const mainEl = document.getElementById('main-content');
    let sectionObserver: IntersectionObserver | null = null;

    if (mainEl) {
      const tintMap: Record<string, string> = {
        'start-grid': 'neutral',
        'session-proof': 'warm',
        's1-pain': 'cool',
        's2-versus': 'warm',
        's3-product': 'gold',
        'sim-first': 'cool',
        'premium': 'gold',
        'garage': 'warm',
        'pit-stop': 'neutral',
        'podium': 'gold',
      };

      sectionObserver = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const tint = tintMap[entry.target.id] || 'neutral';
              mainEl.setAttribute('data-bg-tint', tint);
            }
          });
        },
        { threshold: 0.3 },
      );

      sections.forEach((s) => sectionObserver!.observe(s));
    }

    return () => {
      ScrollTrigger.getAll().forEach((st) => st.kill());
      sectionObserver?.disconnect();
      if (skewTickerActive) {
        // Ticker cleanup handled by GSAP on page unload
      }
    };
  }, [reducedMotion]);

  return null;
}
