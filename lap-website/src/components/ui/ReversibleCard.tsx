'use client';

import { useState } from 'react';

interface ReversibleCardProps {
  title: string;
  description: string;
  className?: string;
}

export function ReversibleCard({ title, description, className = '' }: ReversibleCardProps) {
  const [flipped, setFlipped] = useState(false);

  return (
    <article
      className={`relative border border-steel/20 bg-concrete/35 p-5 cursor-pointer ${className}`}
      style={{ perspective: '900px' }}
      onClick={() => setFlipped((value) => !value)}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          setFlipped((value) => !value);
        }
      }}
      aria-label={`Flip card for ${title}`}
    >
      <div
        className="relative min-h-[120px] transition-transform duration-[620ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          transformStyle: 'preserve-3d',
          transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
      >
        <div className="absolute inset-0" style={{ backfaceVisibility: 'hidden' }}>
          <p className="font-monument text-[var(--text-h3)] leading-[0.9]">{title}</p>
          <p className="mt-3 font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase">
            Click to reveal
          </p>
        </div>
        <div
          className="absolute inset-0 text-steel"
          style={{ backfaceVisibility: 'hidden', transform: 'rotateY(180deg)' }}
        >
          <p className="text-sm md:text-base leading-relaxed">{description}</p>
          <p className="mt-3 font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase">
            Click to close
          </p>
        </div>
      </div>
    </article>
  );
}
