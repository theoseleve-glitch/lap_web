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
    <div ref={containerRef} className="texture-grain min-h-screen relative">
      <div
        className="pointer-events-none fixed inset-0 z-0 transition-opacity duration-1000"
        style={{
          background: `radial-gradient(circle 120px at var(--pointer-x, 50%) var(--pointer-y, 50%), rgba(217, 70, 239, 0.08) 0%, transparent 100%)`,
        }}
      />
      {/* SVG track outline — simplified racing line at very low opacity */}
      <svg
        className="pointer-events-none fixed inset-0 z-0"
        viewBox="-7 -5 14 10"
        preserveAspectRatio="xMidYMid meet"
        aria-hidden="true"
        style={{ width: '100%', height: '100%' }}
      >
        <defs>
          <linearGradient id="fallback-track-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#D946EF" stopOpacity="0.06" />
            <stop offset="50%" stopColor="#B6FF2E" stopOpacity="0.04" />
            <stop offset="100%" stopColor="#D946EF" stopOpacity="0.06" />
          </linearGradient>
        </defs>
        <path
          d="M-5.5,3.2 C-3,3.5 -0.5,3.8 1.8,3 C3.5,1.8 4.8,0.2 5.2,-1.5 C4,-2.8 2,-3.2 0,-3.5 C-2,-3 -3.8,-2 -4.8,-0.5 C-5.2,0.8 -5.5,2 -5.8,2.8 Z"
          fill="none"
          stroke="url(#fallback-track-gradient)"
          strokeWidth="0.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            animation: 'fallbackTrackPulse 3s ease-in-out infinite',
          }}
        />
        <style>{`
          @keyframes fallbackTrackPulse {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; }
          }
        `}</style>
      </svg>
      {safetyCarActive && (
        <div
          className="fixed top-4 left-1/2 -translate-x-1/2 z-50 font-telemetry text-[11px] tracking-[0.3em] uppercase px-4 py-1.5 rounded-full border pointer-events-none"
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
