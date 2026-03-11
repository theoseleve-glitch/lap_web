'use client';

import { useState } from 'react';
import type { FocusArea } from './types';

interface DeferredAreasProps {
  areas?: FocusArea[] | null;
}

export default function DeferredAreas({ areas }: DeferredAreasProps) {
  const [open, setOpen] = useState(false);

  if (!areas || areas.length === 0) return null;

  return (
    <div className="bg-asphalt/30 rounded-xl border border-steel/5 p-5">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between text-left"
      >
        <h3 className="text-xs text-steel font-body uppercase tracking-wider">
          For Later ({areas.length})
        </h3>
        <span className="text-steel text-xs transform transition-transform" style={{ transform: open ? 'rotate(180deg)' : 'none' }}>
          v
        </span>
      </button>

      {open && (
        <ul className="mt-4 space-y-3">
          {areas.map((area, i) => (
            <li key={i} className="flex items-start gap-3">
              <span className="text-steel/50 text-xs font-telemetry shrink-0 mt-0.5">
                {area.category}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-chalk/50 font-body leading-relaxed">{area.summary}</p>
                {area.time_loss_s != null && (
                  <span className="text-xs font-telemetry text-steel/40 mt-1 inline-block">
                    +{area.time_loss_s.toFixed(3)}s
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
