'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

interface FallbackShellProps {
  children: ReactNode;
}

export function FallbackShell({ children }: FallbackShellProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const safetyCarActive = useKernelStore((s) => s.safetyCar.active);

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
    <div ref={containerRef} className="min-h-screen relative bg-black">
      {safetyCarActive && (
        <div
          className="fixed top-4 left-1/2 -translate-x-1/2 z-50 font-telemetry text-[11px] tracking-[0.3em] uppercase px-4 py-1.5 border pointer-events-none"
          style={{
            color: colors.marshalYellow,
            backgroundColor: `${colors.asphalt}CC`,
            borderColor: `${colors.marshalYellow}4D`,
          }}
        >
          Safety Car
        </div>
      )}
      {children}
    </div>
  );
}
