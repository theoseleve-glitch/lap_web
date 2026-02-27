'use client';

import { useEffect, useRef, type ReactNode } from 'react';

interface FallbackShellProps {
  children: ReactNode;
}

export function FallbackShell({ children }: FallbackShellProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function handleMove(e: PointerEvent) {
      const x = ((e.clientX / window.innerWidth) * 100).toFixed(1);
      const y = ((e.clientY / window.innerHeight) * 100).toFixed(1);
      el!.style.setProperty('--pointer-x', `${x}%`);
      el!.style.setProperty('--pointer-y', `${y}%`);
    }

    window.addEventListener('pointermove', handleMove, { passive: true });
    return () => window.removeEventListener('pointermove', handleMove);
  }, []);

  return (
    <div ref={containerRef} className="texture-grain min-h-screen relative">
      <div
        className="pointer-events-none fixed inset-0 z-0 transition-opacity duration-1000"
        style={{
          background: `radial-gradient(circle 120px at var(--pointer-x, 50%) var(--pointer-y, 50%), rgba(217, 70, 239, 0.08) 0%, transparent 100%)`,
        }}
      />
      {children}
    </div>
  );
}
