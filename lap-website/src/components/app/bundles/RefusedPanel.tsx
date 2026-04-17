'use client';

import { getSupportLevel } from '@/lib/bundle-vocabulary';
import { SupportLevelBadge } from './SupportLevelBadge';

interface Props {
  tier: string;
  reason?: string | null;
}

export function RefusedPanel({ tier, reason }: Props) {
  const level = getSupportLevel(tier);

  return (
    <div className="rounded-xl border border-safety-red/30 bg-safety-red/5 p-5">
      <div className="flex items-center gap-3 mb-3">
        <SupportLevelBadge tier={tier} size="md" />
        <h3 className="text-sm font-monument text-chalk">
          Analysis Not Available
        </h3>
      </div>
      <p className="text-sm font-body text-steel">
        {level.description}
      </p>
      {reason && (
        <p className="mt-2 text-xs font-telemetry text-steel/70">
          Reason: {reason.replace(/_/g, ' ')}
        </p>
      )}
    </div>
  );
}
