'use client';

import { useState } from 'react';
import Image from 'next/image';

interface AudienceChooserProps {
  onChoose: (persona: string) => void;
}

export function AudienceChooser({ onChoose }: AudienceChooserProps) {
  const [hovered, setHovered] = useState<'driver' | 'venue' | null>(null);

  function chooseDriver() {
    document.cookie = `lap_persona=drivers;path=/;max-age=${60 * 60 * 24 * 365};SameSite=Lax`;
    onChoose('drivers');
  }

  function chooseVenue() {
    window.location.href = '/contact?plan=venues';
  }

  return (
    <section
      id="main-content"
      className="fixed inset-0 z-50 flex flex-col md:flex-row"
      aria-label="Choose your experience"
    >
      {/* Driver half */}
      <button
        type="button"
        className={`
          relative flex-1 flex flex-col items-center justify-center gap-6 p-8
          bg-asphalt border-b md:border-b-0 md:border-r border-chalk/10
          transition-all duration-500 cursor-pointer group
          ${hovered === 'driver' ? 'md:flex-[1.1]' : ''}
          ${hovered === 'venue' ? 'md:flex-[0.9]' : ''}
        `}
        onMouseEnter={() => setHovered('driver')}
        onMouseLeave={() => setHovered(null)}
        onClick={chooseDriver}
      >
        <div className={`transition-transform duration-500 ${hovered === 'driver' ? 'scale-110' : ''}`}>
          <Image
            src="/logo/front_page_driver.svg"
            alt="Driver icon"
            className="w-24 h-16 md:w-32 md:h-20 object-contain"
            width={192}
            height={128}
            unoptimized
            priority
          />
        </div>
        <h2 className="font-monument text-[clamp(24px,4vw,48px)] text-chalk leading-tight">
          FOR DRIVERS
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
        type="button"
        className={`
          relative flex-1 flex flex-col items-center justify-center gap-6 p-8
          bg-concrete transition-all duration-500 cursor-pointer group
          ${hovered === 'venue' ? 'md:flex-[1.1]' : ''}
          ${hovered === 'driver' ? 'md:flex-[0.9]' : ''}
        `}
        onMouseEnter={() => setHovered('venue')}
        onMouseLeave={() => setHovered(null)}
        onClick={chooseVenue}
      >
        <div className={`transition-transform duration-500 ${hovered === 'venue' ? 'scale-110' : ''}`}>
          <Image
            src="/logo/front_page_venue.svg"
            alt="Venue icon"
            className="w-24 h-16 md:w-32 md:h-20 object-contain"
            width={192}
            height={128}
            unoptimized
            priority
          />
        </div>
        <h2 className="font-monument text-[clamp(24px,4vw,48px)] text-chalk leading-tight">
          FOR VENUES
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
