'use client';

import { useState, useCallback } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { garage } from '@/data/copy';
import { trackGaragePanelExpand } from '@/lib/analytics';

export function Garage() {
  const [openPanel, setOpenPanel] = useState<number | null>(null);

  const togglePanel = useCallback((index: number) => {
    const next = openPanel === index ? null : index;
    setOpenPanel(next);
    if (next !== null) trackGaragePanelExpand(garage.panels[next].title);
  }, [openPanel]);

  return (
    <section
      id="garage"
      data-accent="none"
      className="relative py-16 md:py-24"
      style={{
        minHeight: '100vh',
        backgroundImage: `
          linear-gradient(rgba(138, 143, 152, 0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(138, 143, 152, 0.04) 1px, transparent 1px)
        `,
        backgroundSize: '48px 48px',
      }}
      aria-label="Garage — Technical documentation"
    >
      <div className="grid-lap">
        <div className="col-span-full text-center mb-4">
          <MonumentText size="h1" as="h2">
            {garage.monument}
          </MonumentText>
        </div>
        <div className="col-span-full text-center mb-12">
          <p className="font-telemetry text-steel">{garage.subhead}</p>
        </div>

        <div className="col-span-full max-w-3xl mx-auto">
          {garage.panels.map((panel, i) => (
            <div key={panel.title} className="border-b border-steel/20">
              <button
                className="w-full flex items-center justify-between py-4 text-left font-monument text-[var(--text-h3)] hover:text-chalk transition-colors duration-300"
                onClick={() => togglePanel(i)}
                aria-expanded={openPanel === i}
              >
                {panel.title}
                <span
                  className="text-steel text-xl transition-transform duration-[420ms]"
                  style={{ transform: openPanel === i ? 'rotate(45deg)' : 'rotate(0deg)' }}
                >
                  +
                </span>
              </button>
              <div
                className="grid transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
                style={{ gridTemplateRows: openPanel === i ? '1fr' : '0fr' }}
              >
                <div className="overflow-hidden">
                  <div className="pb-6 font-telemetry text-steel text-[11px] tracking-[0.12em] leading-relaxed whitespace-pre-line">
                    {panel.content}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
