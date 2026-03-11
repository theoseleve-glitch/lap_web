'use client';

import type { WarmUpProtocol as WarmUpData } from './types';

interface WarmUpProtocolProps {
  protocol?: WarmUpData | null;
}

const PHASE_LABELS = ['Sighting Laps', 'Build Laps', 'Push'];
const PHASE_COLORS = [
  'border-blue-500/40 bg-blue-500/5',
  'border-yellow-500/40 bg-yellow-500/5',
  'border-emerald-500/40 bg-emerald-500/5',
];

export default function WarmUpProtocol({ protocol }: WarmUpProtocolProps) {
  if (!protocol) return null;

  const phases = [
    { laps: protocol.phase_1_laps, instruction: protocol.phase_1_instruction },
    { laps: protocol.phase_2_laps, instruction: protocol.phase_2_instruction },
    { laps: null, instruction: protocol.phase_3_instruction },
  ];

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-monument text-chalk/80 uppercase tracking-wider">
        Warm-Up Protocol
      </h3>
      <div className="space-y-1.5">
        {phases.map((phase, i) => (
          <div
            key={i}
            className={`border-l-2 ${PHASE_COLORS[i]} rounded-r-md px-3 py-2`}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-telemetry text-chalk/60">
                Phase {i + 1}
              </span>
              <span className="text-xs font-monument text-chalk/90">
                {PHASE_LABELS[i]}
                {phase.laps != null && ` (${phase.laps} laps)`}
              </span>
            </div>
            {phase.instruction && (
              <p className="text-xs text-chalk/70 font-body mt-0.5 leading-relaxed">
                {phase.instruction}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
