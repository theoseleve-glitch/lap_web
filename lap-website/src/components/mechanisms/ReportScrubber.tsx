'use client';

import { useState, useCallback, type CSSProperties } from 'react';
import Image from 'next/image';
import { trackS3ScrubberInteract } from '@/lib/analytics';

interface ReportScrubberProps {
  className?: string;
  panels?: ScrubberPanel[];
  ariaLabel?: string;
  accentColor?: string;
}

export interface ScrubberPanel {
  label: string;
  description: string;
  image: string;
  alt: string;
}

const defaultPanels: ScrubberPanel[] = [
  {
    label: 'SCORE OVERVIEW',
    description: 'Four-pillar scoring: Pace, Consistency, Execution, Robustness. Grade A at 86/100.',
    image: '/images/screenshots/score-overview.png',
    alt: 'Session score overview showing four performance pillars',
  },
  {
    label: 'CORNER COACHING',
    description: 'Corner-by-corner analysis with brake point, apex speed, and exit drive breakdowns.',
    image: '/images/screenshots/corner-replay.png',
    alt: 'Corner replay with cockpit gauges and track map',
  },
  {
    label: 'LAP DATA',
    description: 'Full lap-by-lap telemetry table. Best lap highlighted. Speed, braking, line distance tracked.',
    image: '/images/screenshots/lap-table.png',
    alt: 'Lap data table with best lap highlighted',
  },
];

export function ReportScrubber({
  className = '',
  panels = defaultPanels,
  ariaLabel = 'Scrub through report views',
  accentColor = 'var(--accent)',
}: ReportScrubberProps) {
  const [position, setPosition] = useState(0);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    setPosition(val);
    trackS3ScrubberInteract(val);
  }, []);

  return (
    <div className={`${className}`} style={{ '--accent': accentColor } as CSSProperties}>
      {/* Screenshot with art direction: grayscale + grain + single accent */}
      <div
        className="relative w-full aspect-video bg-concrete border border-chalk/15 overflow-hidden mb-6"
      >
        {panels.map((panel, i) => (
          <div
            key={panel.label}
            className="absolute inset-0 transition-opacity duration-[420ms]"
            style={{ opacity: i === position ? 1 : 0 }}
            aria-hidden={i !== position}
          >
            <Image
              src={panel.image}
              alt={panel.alt}
              fill
              sizes="(max-width: 768px) 100vw, 768px"
              className="object-cover object-top"
              style={{ filter: 'grayscale(0.85) contrast(1.1) brightness(0.9)' }}
              priority={i === 0}
            />
          </div>
        ))}
        {/* Grain overlay */}
        <div
          className="absolute inset-0 pointer-events-none opacity-[0.04] mix-blend-overlay"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E")`,
          }}
        />
        {/* Accent tint line */}
        <div
          className="absolute bottom-0 left-0 h-[3px] bg-[var(--accent)] transition-all duration-[420ms]"
          style={{ width: `${((position + 1) / panels.length) * 100}%` }}
        />
        {/* Telemetry label overlay */}
        <div className="absolute top-3 left-3 font-telemetry text-[11px] tracking-[0.12em] uppercase text-[var(--accent)] opacity-80">
          {panels[position].label}
        </div>
      </div>

      {/* Scrubber */}
      <div className="px-4 mb-6">
        <input
          type="range"
          min="0"
          max={panels.length - 1}
          step="1"
          value={position}
          onChange={handleChange}
          className="w-full h-1 appearance-none bg-concrete rounded-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-chalk
            [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:bg-chalk [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:rounded-none"
          aria-label={ariaLabel}
        />
        <div className="flex justify-between mt-2">
          {panels.map((p, i) => (
            <span
              key={p.label}
              className={`font-telemetry text-[9px] tracking-[0.12em] uppercase transition-colors duration-300 ${
                i === position ? 'text-[var(--accent)]' : 'text-steel'
              }`}
            >
              {p.label}
            </span>
          ))}
        </div>
      </div>

      {/* Panel content */}
      <div className="bg-concrete p-6 transition-opacity duration-[420ms]">
        <h4 className="font-monument text-[var(--text-h3)] mb-2">{panels[position].label}</h4>
        <p className="font-body text-steel leading-relaxed">{panels[position].description}</p>
      </div>
    </div>
  );
}
