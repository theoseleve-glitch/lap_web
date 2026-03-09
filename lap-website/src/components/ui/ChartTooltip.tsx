/**
 * ChartTooltip.tsx — Contextual help tooltips for chart panels.
 *
 * Small "?" button that shows a tooltip explaining what the chart shows
 * and how to interact with it.
 */
'use client';

import { useState, useRef, useEffect } from 'react';

interface Props {
  title: string;
  description: string;
  tips?: string[];
}

export function ChartTooltip({ title, description, tips }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-5 h-5 rounded-full border border-steel/20 text-steel text-[10px] font-telemetry
          hover:text-chalk hover:border-steel/40 transition-colors flex items-center justify-center"
        aria-label={`Help: ${title}`}
        title={`What is ${title}?`}
      >
        ?
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 w-64 bg-concrete border border-steel/20 rounded-lg p-3 shadow-xl">
          <h4 className="text-xs font-monument text-chalk mb-1">{title}</h4>
          <p className="text-[11px] font-body text-steel leading-relaxed mb-2">{description}</p>
          {tips && tips.length > 0 && (
            <div className="border-t border-steel/10 pt-2">
              <p className="text-[9px] font-telemetry text-steel/60 uppercase tracking-wider mb-1">Tips</p>
              <ul className="space-y-1">
                {tips.map((tip, i) => (
                  <li key={i} className="text-[10px] font-body text-steel/80 flex gap-1">
                    <span className="text-pit-orange shrink-0">*</span>
                    {tip}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
