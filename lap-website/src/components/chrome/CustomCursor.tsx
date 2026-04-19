'use client';

import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from '@/hooks/useReducedMotion';

type CursorState = 'default' | 'hover' | 'text';

export function CustomCursor() {
  const cursorRef = useRef<HTMLDivElement>(null);
  const { reducedMotion } = useReducedMotion();
  const [state, setState] = useState<CursorState>('default');
  const [label, setLabel] = useState('');
  const [isVisible, setIsVisible] = useState(false);

  // Lerped cursor position for smooth follow
  const pos = useRef({ x: 0, y: 0 });
  const target = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (window.matchMedia('(pointer: coarse)').matches) return;
    if (reducedMotion) return;

    setIsVisible(true);
    document.body.style.cursor = 'none';

    const handleMove = (e: MouseEvent) => {
      target.current.x = e.clientX;
      target.current.y = e.clientY;
    };

    const handleOver = (e: MouseEvent) => {
      const el = e.target as HTMLElement;

      // Check for data-cursor attribute first (explicit label)
      const cursorEl = el.closest('[data-cursor]') as HTMLElement | null;
      if (cursorEl) {
        setState('text');
        setLabel(cursorEl.dataset.cursor || '');
        return;
      }

      // Standard interactive elements
      const isInteractive = el.closest('a, button, [role="button"], input, select, [tabindex]');
      if (isInteractive) {
        setState('hover');
        setLabel('');
        return;
      }

      setState('default');
      setLabel('');
    };

    // Smooth position interpolation via rAF
    let rafId: number;
    const lerp = () => {
      pos.current.x += (target.current.x - pos.current.x) * 0.15;
      pos.current.y += (target.current.y - pos.current.y) * 0.15;

      if (cursorRef.current) {
        cursorRef.current.style.transform = `translate(${pos.current.x}px, ${pos.current.y}px)`;
      }
      rafId = requestAnimationFrame(lerp);
    };
    rafId = requestAnimationFrame(lerp);

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseover', handleOver);

    return () => {
      document.body.style.cursor = '';
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseover', handleOver);
      cancelAnimationFrame(rafId);
    };
  }, [reducedMotion]);

  if (!isVisible) return null;

  const sizes = {
    default: { width: 8, height: 8 },
    hover: { width: 28, height: 28 },
    text: { width: 56, height: 56 },
  };

  const size = sizes[state];

  return (
    <div
      ref={cursorRef}
      className="fixed top-0 left-0 pointer-events-none z-[999] -translate-x-1/2 -translate-y-1/2"
      style={{ willChange: 'transform' }}
      aria-hidden="true"
    >
      <div
        className="rounded-full border border-[var(--accent)] flex items-center justify-center transition-all duration-300 ease-[var(--ease-spring)]"
        style={{
          width: size.width,
          height: size.height,
          boxShadow: `0 0 ${state === 'default' ? '4px' : '12px'} var(--accent)`,
          opacity: 0.85,
          background: state === 'text' ? 'rgba(201, 168, 76, 0.1)' : 'transparent',
        }}
      >
        {state === 'text' && label && (
          <span className="font-telemetry text-[8px] tracking-[0.15em] uppercase text-gold select-none">
            {label}
          </span>
        )}
      </div>
    </div>
  );
}
