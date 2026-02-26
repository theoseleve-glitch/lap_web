'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { Tooltip } from '@/components/ui/Tooltip';
import { TelemetryTraces } from '@/components/mechanisms/TelemetryTraces';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { s1Deep } from '@/data/copy';
import { colors } from '@/lib/tokens';
import { useGpuCapability } from '@/hooks/useGpuCapability';
import { trackS1DeepTraceHover } from '@/lib/analytics';

export function S1DeepSculpture() {
  const [hoveredTrace, setHoveredTrace] = useState<string | null>(null);
  const { hasWebGL } = useGpuCapability();

  const handleTraceHover = useCallback((trace: string | null) => {
    setHoveredTrace(trace);
    if (trace) trackS1DeepTraceHover(trace);
  }, []);

  const tooltipMap: Record<string, string> = {
    speed: s1Deep.tooltips.speed,
    brake: s1Deep.tooltips.brake,
    steering: s1Deep.tooltips.steering,
  };

  return (
    <section
      id="s1-deep"
      data-accent="green"
      className="room relative py-16 md:py-24"
      aria-label="Sector 1 — Telemetry as sculpture"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-8">
          <MonumentText size="h1" as="h2" reveal>
            {s1Deep.monument}
          </MonumentText>
        </div>

        <div className="col-span-full mb-6">
          <TelemetryTraces
            progress={1}
            hoveredTrace={hoveredTrace}
            onTraceHover={handleTraceHover}
            useWebGL={hasWebGL}
          />
        </div>

        <div className="col-span-full">
          <ReversibleCard
            title="Telemetry Made Actionable"
            description={s1Deep.body}
            className="max-w-2xl mx-auto mb-6"
          />

          {/* Trace legend with tooltips */}
          <div className="flex flex-wrap justify-center gap-6">
            <Tooltip content={s1Deep.tooltips.speed}>
              <span
                className="font-telemetry cursor-help flex items-center gap-2"
                style={{ color: hoveredTrace === 'speed' ? colors.chalk : colors.steel }}
                onMouseEnter={() => handleTraceHover('speed')}
                onMouseLeave={() => handleTraceHover(null)}
              >
                <span className="w-4 h-0.5 inline-block" style={{ background: colors.chalk }} />
                SPEED
              </span>
            </Tooltip>
            <Tooltip content={s1Deep.tooltips.brake}>
              <span
                className="font-telemetry cursor-help flex items-center gap-2"
                style={{ color: hoveredTrace === 'brake' ? colors.safetyRed : colors.steel }}
                onMouseEnter={() => handleTraceHover('brake')}
                onMouseLeave={() => handleTraceHover(null)}
              >
                <span className="w-4 h-0.5 inline-block" style={{ background: colors.safetyRed }} />
                BRAKE
              </span>
            </Tooltip>
            <Tooltip content={s1Deep.tooltips.steering}>
              <span
                className="font-telemetry cursor-help flex items-center gap-2"
                style={{ color: hoveredTrace === 'steering' ? colors.steel : colors.steel }}
                onMouseEnter={() => handleTraceHover('steering')}
                onMouseLeave={() => handleTraceHover(null)}
              >
                <span className="w-4 h-0.5 inline-block" style={{ background: colors.steel }} />
                STEERING
              </span>
            </Tooltip>
          </div>

          {/* Active tooltip display */}
          {hoveredTrace && (
            <div className="mt-4 text-center">
              <p className="font-telemetry text-[var(--accent)] inline-block bg-concrete px-4 py-2">
                {tooltipMap[hoveredTrace]}
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
