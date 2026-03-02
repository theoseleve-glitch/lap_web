'use client';

import { useState } from 'react';

/* ── Inline SVG: Helmet icon ─────────────────── */
function HelmetIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      className={className}
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 40c0-11 9-24 20-24s20 13 20 24" />
      <path d="M12 40c0 6 3 10 8 12h24c5-2 8-6 8-12" />
      <path d="M12 40h14l4-6h4l4 6h14" />
      <circle cx="42" cy="36" r="2" fill="currentColor" />
    </svg>
  );
}

/* ── Inline SVG: Track layout icon ───────────── */
function TrackIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      className={className}
      width="64"
      height="64"
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 48 C8 36 8 20 20 12 C32 4 48 8 52 20 C56 32 48 36 40 32 C32 28 28 20 36 16 C44 12 48 20 44 28" />
      <circle cx="16" cy="48" r="3" fill="currentColor" />
    </svg>
  );
}

interface AudienceChooserProps {
  onChoose: (persona: string) => void;
}

export function AudienceChooser({ onChoose }: AudienceChooserProps) {
  const [hovered, setHovered] = useState<'driver' | 'venue' | null>(null);

  function choose(persona: string) {
    document.cookie = `lap_persona=${persona};path=/;max-age=${60 * 60 * 24 * 365};SameSite=Lax`;
    onChoose(persona);
  }

  return (
    <section
      id="main-content"
      className="fixed inset-0 z-50 flex flex-col md:flex-row"
      aria-label="Choose your experience"
    >
      {/* Driver half */}
      <button
        className={`
          relative flex-1 flex flex-col items-center justify-center gap-6 p-8
          bg-asphalt border-b md:border-b-0 md:border-r border-chalk/10
          transition-all duration-500 cursor-pointer group
          ${hovered === 'driver' ? 'md:flex-[1.1]' : ''}
          ${hovered === 'venue' ? 'md:flex-[0.9]' : ''}
        `}
        onMouseEnter={() => setHovered('driver')}
        onMouseLeave={() => setHovered(null)}
        onClick={() => choose('drivers')}
      >
        <div className={`transition-transform duration-500 ${hovered === 'driver' ? 'scale-110' : ''}`}>
          <HelmetIcon className="text-chalk w-16 h-16 md:w-20 md:h-20" />
        </div>
        <h2 className="font-monument text-[clamp(24px,4vw,48px)] text-chalk leading-tight">
          I&apos;M A DRIVER
        </h2>
        <p className="font-telemetry text-steel text-sm tracking-widest max-w-xs text-center">
          FIND WHERE YOU LOSE TIME. GET FASTER.
        </p>
        <div
          className={`absolute bottom-0 left-0 right-0 h-1 bg-acid-green transition-opacity duration-500 ${
            hovered === 'driver' ? 'opacity-100' : 'opacity-0'
          }`}
        />
      </button>

      {/* Venue half */}
      <button
        className={`
          relative flex-1 flex flex-col items-center justify-center gap-6 p-8
          bg-concrete transition-all duration-500 cursor-pointer group
          ${hovered === 'venue' ? 'md:flex-[1.1]' : ''}
          ${hovered === 'driver' ? 'md:flex-[0.9]' : ''}
        `}
        onMouseEnter={() => setHovered('venue')}
        onMouseLeave={() => setHovered(null)}
        onClick={() => choose('venues')}
      >
        <div className={`transition-transform duration-500 ${hovered === 'venue' ? 'scale-110' : ''}`}>
          <TrackIcon className="text-pit-orange w-16 h-16 md:w-20 md:h-20" />
        </div>
        <h2 className="font-monument text-[clamp(24px,4vw,48px)] text-chalk leading-tight">
          I RUN A VENUE
        </h2>
        <p className="font-telemetry text-steel text-sm tracking-widest max-w-xs text-center">
          ONE ENGINE. YOUR DRIVERS. ZERO STAFF PAIN.
        </p>
        <div
          className={`absolute bottom-0 left-0 right-0 h-1 bg-pit-orange transition-opacity duration-500 ${
            hovered === 'venue' ? 'opacity-100' : 'opacity-0'
          }`}
        />
      </button>
    </section>
  );
}
