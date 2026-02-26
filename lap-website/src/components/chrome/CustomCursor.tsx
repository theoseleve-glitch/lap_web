'use client';

import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from '@/hooks/useReducedMotion';

export function CustomCursor() {
  const cursorRef = useRef<HTMLDivElement>(null);
  const { reducedMotion } = useReducedMotion();
  const [isHovering, setIsHovering] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Hide on touch devices
    if (window.matchMedia('(pointer: coarse)').matches) return;
    if (reducedMotion) return;

    setIsVisible(true);
    document.body.style.cursor = 'none';

    const handleMove = (e: MouseEvent) => {
      if (cursorRef.current) {
        cursorRef.current.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      }
    };

    const handleOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const isInteractive = target.closest('a, button, [role="button"], input, select, [tabindex]');
      setIsHovering(!!isInteractive);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseover', handleOver);

    return () => {
      document.body.style.cursor = '';
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseover', handleOver);
    };
  }, [reducedMotion]);

  if (!isVisible) return null;

  return (
    <div
      ref={cursorRef}
      className="fixed top-0 left-0 pointer-events-none z-[999] -translate-x-1/2 -translate-y-1/2"
      style={{ willChange: 'transform' }}
      aria-hidden="true"
    >
      <div
        className="rounded-full border border-[var(--accent)] transition-all duration-200"
        style={{
          width: isHovering ? '24px' : '8px',
          height: isHovering ? '24px' : '8px',
          boxShadow: `0 0 ${isHovering ? '12px' : '4px'} var(--accent)`,
          opacity: 0.8,
        }}
      />
    </div>
  );
}
