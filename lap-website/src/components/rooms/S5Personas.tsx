'use client';

import { useCallback, useRef } from 'react';
import Link from 'next/link';
import { personaPages } from '@/data/personas';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { TrackCard } from '@/components/ui/TrackCard';
import { useKernelStore } from '@/experience/state/store';

export function S5Personas() {
  const activateDrs = useKernelStore((s) => s.activateDrs);
  const drsTriggered = useRef(false);

  const handlePersonaClick = useCallback(() => {
    if (!drsTriggered.current) {
      drsTriggered.current = true;
      activateDrs('persona-expand');
    }
  }, [activateDrs]);

  return (
    <section
      id="s5-personas"
      data-accent="orange"
      className="room relative py-16 md:py-24 border-t border-steel/20"
      aria-label="Persona pages"
    >
      <div className="grid-lap">
        <div className="col-span-full mb-8">
          <h2 className="font-monument text-[clamp(42px,7vw,76px)] leading-[0.9]">
            PERSONA
            <br />
            LANDING PAGES
          </h2>
          <ReversibleCard
            title="Persona-Specific Journeys"
            description="Drivers, circuits, teams, and endurance programs each get dedicated messaging, proof, and conversion paths aligned to their buying intent."
            className="max-w-2xl mt-4"
          />
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-4">
          {personaPages.map((persona) => (
            <TrackCard
              key={persona.slug}
              title={persona.title}
              description={persona.subtitle}
              onClick={handlePersonaClick}
            >
              <div className="flex flex-wrap gap-2">
                <Link
                  href={`/${persona.slug}`}
                  className="border border-chalk/50 px-3 py-1 text-xs font-telemetry tracking-[0.12em]"
                  onClick={(e) => e.stopPropagation()}
                >
                  OPEN PAGE
                </Link>
                <Link
                  href={persona.primaryCta.href}
                  className="border border-pit-orange px-3 py-1 text-xs font-telemetry tracking-[0.12em]"
                  onClick={(e) => e.stopPropagation()}
                >
                  {persona.primaryCta.label.toUpperCase()}
                </Link>
              </div>
            </TrackCard>
          ))}
        </div>
      </div>
    </section>
  );
}
