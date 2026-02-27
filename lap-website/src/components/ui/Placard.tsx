'use client';

import { useState, useRef, useCallback } from 'react';
import { ScrutineeringStamp } from './ScrutineeringStamp';
import { useKernelStore } from '@/experience/state/store';

interface PlacardProps {
  title: string;
  children: React.ReactNode;
  revealContent?: React.ReactNode;
  stamp?: { label: string; detail: string };
  className?: string;
}

export function Placard({
  title,
  children,
  revealContent,
  stamp,
  className = '',
}: PlacardProps) {
  const [flipped, setFlipped] = useState(false);
  const drsTriggered = useRef(false);
  const activateDrs = useKernelStore((s) => s.activateDrs);

  const handleReveal = useCallback(() => {
    setFlipped(true);
    if (!drsTriggered.current) {
      drsTriggered.current = true;
      activateDrs('card-reveal');
    }
  }, [activateDrs]);

  return (
    <div
      className={`relative bg-concrete p-6 ${className}`}
      style={{ perspective: revealContent ? '800px' : undefined }}
    >
      <div
        className="transition-transform duration-[900ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          transformStyle: revealContent ? 'preserve-3d' : undefined,
          transform: revealContent ? (flipped ? 'rotateY(180deg)' : 'rotateY(0deg)') : undefined,
        }}
      >
        {/* Front — inert when flipped to prevent hidden-face focus trap */}
        <div
          style={{ backfaceVisibility: revealContent ? 'hidden' : undefined }}
          {...(revealContent && flipped ? { inert: '' as unknown as boolean } : {})}
        >
          <h3 className="font-monument text-[var(--text-h3)] mb-3">{title}</h3>
          <div className="font-body text-steel leading-relaxed">{children}</div>
          {stamp && (
            <div className="mt-4">
              <ScrutineeringStamp label={stamp.label} detail={stamp.detail} />
            </div>
          )}
          {revealContent && (
            <button
              className="mt-4 font-telemetry text-[11px] tracking-[0.12em] uppercase text-[var(--accent)] hover:underline"
              onClick={handleReveal}
              aria-expanded={flipped}
              aria-label={`Reveal ${title}`}
            >
              REVEAL
            </button>
          )}
        </div>

        {/* Back — inert when not flipped to prevent hidden-face focus trap */}
        {revealContent && (
          <div
            className="absolute inset-0 bg-concrete p-6 overflow-y-auto"
            style={{
              backfaceVisibility: 'hidden',
              transform: 'rotateY(180deg)',
            }}
            {...(!flipped ? { inert: '' as unknown as boolean } : {})}
          >
            <div className="font-body text-steel leading-relaxed text-sm">{revealContent}</div>
            <button
              className="mt-4 font-telemetry text-[11px] tracking-[0.12em] uppercase text-[var(--accent)] hover:underline"
              onClick={() => setFlipped(false)}
              aria-label={`Close ${title}`}
            >
              CLOSE
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
