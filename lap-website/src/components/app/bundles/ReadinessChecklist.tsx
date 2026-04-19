'use client';

import type { ReadinessSummary } from '@/types/bundles';
import { getReadinessLabel } from '@/lib/bundle-vocabulary';

const CHECKS = [
  { key: 'unknown_sim', label: 'Simulator recognized' },
  { key: 'vehicle_spec_incomplete', label: 'Vehicle data complete' },
  { key: 'vehicle_spec_invalid', label: 'Vehicle data valid' },
  { key: 'track_spec_incomplete', label: 'Track information complete' },
  { key: 'track_spec_invalid', label: 'Track information valid' },
  { key: 'no_telemetry_file', label: 'Telemetry data present' },
  { key: 'no_analysis_json', label: 'Analysis metadata present' },
];

interface Props {
  readiness: ReadinessSummary;
}

export function ReadinessChecklist({ readiness }: Props) {
  const failed = new Set(readiness.reasons);

  // Only show checks that are relevant (failed ones + 3 always-shown)
  const visible = CHECKS.filter(
    (c) => failed.has(c.key) || ['unknown_sim', 'vehicle_spec_incomplete', 'no_telemetry_file'].includes(c.key),
  );

  return (
    <ul className="space-y-1.5">
      {visible.map((check) => {
        const ok = !failed.has(check.key);
        return (
          <li key={check.key} className="flex items-center gap-2 text-sm font-body">
            <span className={ok ? 'text-acid-green' : 'text-safety-red'}>
              {ok ? '\u2713' : '\u2717'}
            </span>
            <span className={ok ? 'text-steel' : 'text-chalk'}>
              {ok ? check.label : getReadinessLabel(check.key)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
