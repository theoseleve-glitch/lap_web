'use client';

import { MonumentText } from '@/components/ui/MonumentText';
import { Placard } from '@/components/ui/Placard';
import { s2Proof } from '@/data/copy';

export function S2Proof() {
  return (
    <section
      id="s2-proof"
      data-accent="yellow"
      className="room relative py-16 md:py-24"
      aria-label="Sector 2 — Scrutineering and proof"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2" reveal>
            {s2Proof.monument}
          </MonumentText>
        </div>

        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel">{s2Proof.subhead}</p>
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-3 gap-6">
          {s2Proof.plates.map((plate) => (
            <Placard
              key={plate.title}
              title={plate.title}
              revealContent={
                <p className="text-sm leading-relaxed">{plate.reveal}</p>
              }
              stamp={plate.stamp}
            >
              <p>{plate.front}</p>
            </Placard>
          ))}
        </div>
      </div>
    </section>
  );
}
