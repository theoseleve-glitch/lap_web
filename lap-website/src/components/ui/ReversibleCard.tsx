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
      className={`relative border border-chalk/15 bg-concrete p-5 cursor-pointer ${className}`}
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
        className="relative transition-transform duration-[620ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          transformStyle: 'preserve-3d',
          transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
      >
        {/* Front face — relative so it establishes the card's dimensions */}
        <div className="flex flex-col items-center justify-center text-center py-6" style={{ backfaceVisibility: 'hidden' }}>
          <p className="font-monument text-[var(--text-h3)] leading-[0.9]">{title}</p>
          <p className="mt-3 font-telemetry text-[10px] tracking-[0.12em] text-steel uppercase">
            Click to reveal
          </p>
        </div>
        {/* Back face — absolute overlay, same size as front */}
        <div
          className="absolute inset-0 flex flex-col items-center justify-center text-center text-steel px-4"
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
