'use client';

import { useState } from 'react';
import type { FocusArea } from './types';

interface FocusAreaCardProps {
  area: FocusArea;
}

const CATEGORY_ICONS: Record<string, string> = {
  braking: '!',
  throttle: '>',
  line: '~',
  consistency: '=',
  cornering: '<',
  default: '*',
};

export default function FocusAreaCard({ area }: FocusAreaCardProps) {
  const [expanded, setExpanded] = useState(false);

  const icon = CATEGORY_ICONS[area.category?.toLowerCase()] ?? CATEGORY_ICONS.default;
  const hasSteps = area.progressive_steps && area.progressive_steps.length > 0;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-5">
      <div className="flex items-start gap-3 mb-3">
        <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-asphalt text-acid-green font-monument text-sm shrink-0">
          {icon}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="text-sm font-monument text-chalk">{area.category}</h3>
            {area.time_loss_s != null && (
              <span className="text-xs font-telemetry text-safety-red bg-safety-red/10 px-2 py-0.5 rounded-full">
                +{area.time_loss_s.toFixed(3)}s
              </span>
            )}
          </div>
          <p className="text-xs text-chalk/70 font-body leading-relaxed">{area.summary}</p>
        </div>
      </div>

      {/* Affected corners */}
      {area.corner_ids && area.corner_ids.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {area.corner_ids.map((id) => (
            <span
              key={id}
              className="text-xs font-telemetry text-chalk/60 bg-asphalt px-2 py-0.5 rounded"
            >
              T{id}
            </span>
          ))}
        </div>
      )}

      {/* Symptom diagnosis */}
      {area.symptom_diagnosis && (
        <div className="mb-3">
          <span className="text-xs font-telemetry text-marshal-yellow bg-marshal-yellow/10 px-2 py-0.5 rounded-full">
            {area.symptom_diagnosis}
          </span>
        </div>
      )}

      {/* Progressive steps accordion */}
      {hasSteps && (
        <div>
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-steel hover:text-chalk font-body flex items-center gap-1 transition-colors"
          >
            <span className="transform transition-transform" style={{ display: 'inline-block', transform: expanded ? 'rotate(90deg)' : 'none' }}>
              &gt;
            </span>
            {expanded ? 'Hide' : 'Show'} improvement steps
          </button>
          {expanded && (
            <ol className="mt-3 space-y-2">
              {area.progressive_steps!.map((step, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-acid-green/20 text-acid-green text-xs font-telemetry shrink-0">
                    {i + 1}
                  </span>
                  <span className="text-xs text-chalk/80 font-body leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
