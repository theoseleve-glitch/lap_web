'use client';

import { getSupportLevel, PLANNER_MODE_LABELS } from '@/lib/bundle-vocabulary';

const ALL_MODES = ['nominal', 'robust', 'exploitable'] as const;

interface Props {
  tier: string | null | undefined;
}

export function PlannerAvailabilityPanel({ tier }: Props) {
  const level = getSupportLevel(tier);
  const available = new Set(level.plannerModes);

  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5">
      <h3 className="text-sm font-monument text-chalk mb-3">Strategy Modes</h3>
      <ul className="space-y-2">
        {ALL_MODES.map((mode) => {
          const label = PLANNER_MODE_LABELS[mode] ?? mode;
          const unlocked = available.has(label);
          return (
            <li key={mode} className="flex items-center justify-between text-sm">
              <span className={`font-body ${unlocked ? 'text-chalk' : 'text-steel/50'}`}>
                {label}
              </span>
              {unlocked ? (
                <span className="text-acid-green font-telemetry text-xs">Available</span>
              ) : (
                <span className="text-steel/40 font-telemetry text-xs">Locked</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
