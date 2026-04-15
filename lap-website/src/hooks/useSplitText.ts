'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

interface SplitTextOptions {
  trigger?: string | Element;
  stagger?: number;
  scrub?: boolean;
  start?: string;
  disabled?: boolean;
}

/**
 * Splits text content into individual character spans and animates them.
 * Uses safe DOM methods (createElement, appendChild) — no innerHTML.
 */
export function useSplitText<T extends HTMLElement>(options: SplitTextOptions = {}) {
  const ref = useRef<T>(null);
  const {
    stagger = 0.02,
    scrub = false,
    start = 'top 80%',
    disabled = false,
  } = options;

  useEffect(() => {
    if (disabled || !ref.current) return;

    const el = ref.current;

    // Snapshot original nodes so we can restore on cleanup
    const originalNodes: Node[] = [];
    el.childNodes.forEach((n) => originalNodes.push(n.cloneNode(true)));

    // Walk DOM and wrap characters in spans
    const wrapCharacters = (parent: HTMLElement) => {
      const snapshot = Array.from(parent.childNodes);
      // Clear parent using DOM methods
      while (parent.firstChild) parent.removeChild(parent.firstChild);

      snapshot.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          const text = node.textContent || '';
          const words = text.split(/(\s+)/);
          words.forEach((word) => {
            if (/^\s+$/.test(word)) {
              parent.appendChild(document.createTextNode(word));
              return;
            }
            const wordSpan = document.createElement('span');
            wordSpan.style.display = 'inline-block';
            wordSpan.style.overflow = 'hidden';
            word.split('').forEach((char) => {
              const charSpan = document.createElement('span');
              charSpan.textContent = char;
              charSpan.style.display = 'inline-block';
              charSpan.classList.add('split-char');
              wordSpan.appendChild(charSpan);
            });
            parent.appendChild(wordSpan);
          });
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          const srcEl = node as HTMLElement;
          if (srcEl.tagName === 'BR') {
            parent.appendChild(document.createElement('br'));
            return;
          }
          // Clone the element shell (preserves tag, class, style) then recurse
          const clone = srcEl.cloneNode(false) as HTMLElement;
          // Copy children text as characters
          const childText = srcEl.textContent || '';
          if (childText) {
            childText.split('').forEach((char) => {
              if (char === '\n' || char === '\r') return;
              const charSpan = document.createElement('span');
              charSpan.textContent = char;
              charSpan.style.display = 'inline-block';
              charSpan.classList.add('split-char');
              if (char === ' ') charSpan.style.width = '0.3em';
              clone.appendChild(charSpan);
            });
          }
          parent.appendChild(clone);
        }
      });
    };

    wrapCharacters(el);

    const chars = el.querySelectorAll('.split-char');

    const anim = gsap.fromTo(
      chars,
      {
        opacity: 0,
        y: 40,
        rotateX: -40,
      },
      {
        opacity: 1,
        y: 0,
        rotateX: 0,
        duration: scrub ? 1 : 0.6,
        ease: scrub ? 'none' : 'power4.out',
        stagger: scrub ? { each: 1 / Math.max(chars.length, 1) } : stagger,
        scrollTrigger: {
          trigger: options.trigger || el,
          start,
          ...(scrub ? { scrub: 1.5 } : { toggleActions: 'play none none none' }),
        },
      },
    );

    return () => {
      anim.scrollTrigger?.kill();
      anim.kill();
      // Restore original DOM
      while (el.firstChild) el.removeChild(el.firstChild);
      originalNodes.forEach((n) => el.appendChild(n.cloneNode(true)));
    };
  }, [disabled, stagger, scrub, start, options.trigger]);

  return ref;
}
