'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { ScrutineeringStamp } from '@/components/ui/ScrutineeringStamp';
import { RadioCard } from '@/components/ui/RadioCard';
import { CornerDrag } from '@/components/mechanisms/CornerDrag';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { s1Pain } from '@/data/copy';
import { colors } from '@/lib/tokens';
import { trackS1CornerInteract } from '@/lib/analytics';

export function S1Pain() {
  const [delta, setDelta] = useState(0);
  const [hasInteracted, setHasInteracted] = useState(false);

  const handleDeltaChange = useCallback((newDelta: number) => {
    setDelta(newDelta);
    if (!hasInteracted && newDelta !== 0) {
      setHasInteracted(true);
    }
    trackS1CornerInteract(newDelta);
  }, [hasInteracted]);

  return (
    <section
      id="s1-pain"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="Sector 1 — Why time is lost"
    >
      <div className="grid-lap">
        <div className="col-span-full md:col-span-6 flex flex-col justify-center gap-6">
          <MonumentText size="h1" as="h2" reveal>
            {s1Pain.monument[0]}<br />{s1Pain.monument[1]}
          </MonumentText>

          <ReversibleCard
            title="Where Time Is Lost"
            description={s1Pain.body}
            className="max-w-lg"
          />

          <div className="flex flex-col gap-2 mt-2">
            <RadioCard label="ENTRY">
              {s1Pain.tooltips.entry}
            </RadioCard>
            <RadioCard label="APEX">
              {s1Pain.tooltips.apex}
            </RadioCard>
            <RadioCard label="EXIT">
              {s1Pain.tooltips.exit}
            </RadioCard>
          </div>

          {hasInteracted && (
            <div className="mt-4">
              <ScrutineeringStamp
                label={s1Pain.stamp.label}
                detail={s1Pain.stamp.detail}
                variant="slam"
              />
            </div>
          )}
        </div>

        <div className="col-span-full md:col-span-6 flex flex-col items-center justify-center gap-4">
          <CornerDrag onDeltaChange={handleDeltaChange} />

          {/* Live delta readout */}
          <div
            className="font-monument text-[var(--text-h2)] text-center"
            style={{ color: delta <= 0 ? colors.acidGreen : colors.safetyRed }}
            aria-live="polite"
            aria-label={`Corner delta: ${delta >= 0 ? '+' : ''}${delta.toFixed(2)} seconds`}
          >
            {delta >= 0 ? '+' : ''}{delta.toFixed(2)}s
          </div>

          <p className="font-telemetry text-steel text-center">
            DRAG THE POINTS // FIND THE LINE
          </p>
        </div>
      </div>
    </section>
  );
}
