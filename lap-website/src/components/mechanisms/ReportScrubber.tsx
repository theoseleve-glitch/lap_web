'use client';

import { useState, useCallback } from 'react';
import { trackS3ScrubberInteract } from '@/lib/analytics';

interface ReportScrubberProps {
  className?: string;
}

const panels = [
  {
    position: 0,
    label: 'SCORE OVERVIEW',
    description: 'Four-pillar scoring: Pace, Consistency, Execution, Robustness. Grade A at 86/100.',
  },
  {
    position: 1,
    label: 'CORNER COACHING',
    description: 'Corner-by-corner analysis with brake point, apex speed, and exit drive breakdowns.',
  },
  {
    position: 2,
    label: 'DEVELOPMENT PLAN',
    description: 'Next-session drills generated from your weakest areas. Actionable, specific, measurable.',
  },
];

export function ReportScrubber({ className = '' }: ReportScrubberProps) {
  const [position, setPosition] = useState(0);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value, 10);
    setPosition(val);
    trackS3ScrubberInteract(val);
  }, []);

  const activePanel = panels[position];

  return (
    <div className={`${className}`}>
      {/* Screenshot placeholder */}
      <div
        className="relative w-full aspect-video bg-concrete border border-steel/20 overflow-hidden mb-6"
      >
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-monument text-[var(--text-h3)] text-steel/30">
            {activePanel.label}
          </span>
        </div>
        {/* Placeholder for real screenshots (Task 15) */}
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--accent)]" style={{ width: `${((position + 1) / 3) * 100}%` }} />
      </div>

      {/* Scrubber */}
      <div className="px-4 mb-6">
        <input
          type="range"
          min="0"
          max="2"
          step="1"
          value={position}
          onChange={handleChange}
          className="w-full h-1 appearance-none bg-concrete rounded-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:bg-chalk
            [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:bg-chalk [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:rounded-none"
          aria-label="Scrub through report views"
        />
        <div className="flex justify-between mt-2">
          {panels.map((p, i) => (
            <span
              key={i}
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
        <h4 className="font-monument text-[var(--text-h3)] mb-2">{activePanel.label}</h4>
        <p className="font-body text-steel leading-relaxed">{activePanel.description}</p>
      </div>
    </div>
  );
}
