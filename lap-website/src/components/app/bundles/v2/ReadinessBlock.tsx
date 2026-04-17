'use client';

import type { SessionPresentation } from '@/lib/api/bundles/types';

const REASON_LABELS: Record<string, string> = {
  unknown_sim: 'Simulator not recognized',
  vehicle_key_missing: 'Vehicle identifier missing',
  track_key_missing: 'Track identifier missing',
  no_telemetry_file: 'No telemetry data in bundle',
  vehicle_spec_incomplete: 'Vehicle data incomplete',
  track_spec_incomplete: 'Track information incomplete',
};

export function ReadinessBlock({ session }: { session: SessionPresentation }) {
  if (session.readiness === 'ready' && session.blockingReasons.length === 0) {
    return null;  // Don't render when everything is fine
  }

  const isBlocked = session.readiness === 'blocked';
  const borderColor = isBlocked ? 'border-safety-red/30' : 'border-marshal-yellow/30';
  const bgColor = isBlocked ? 'bg-safety-red/5' : 'bg-marshal-yellow/5';
  const headColor = isBlocked ? 'text-safety-red' : 'text-marshal-yellow';
  const heading = isBlocked ? 'Analysis Blocked' : 'Incomplete Session Data';

  return (
    <div className={`rounded-xl border ${borderColor} ${bgColor} p-5`}>
      <h3 className={`text-sm font-monument ${headColor} mb-3`}>{heading}</h3>

      {session.blockingReasons.length > 0 && (
        <ul className="space-y-1.5 mb-3">
          {session.blockingReasons.map((r) => (
            <li key={r} className="flex items-center gap-2 text-sm font-body">
              <span className="text-safety-red">{'\u2717'}</span>
              <span className="text-chalk">{REASON_LABELS[r] ?? r.replace(/_/g, ' ')}</span>
            </li>
          ))}
        </ul>
      )}

      {session.degradedFields.length > 0 && (
        <details className="text-xs text-steel mt-2">
          <summary className="cursor-pointer font-telemetry hover:text-chalk transition-colors">
            Degraded fields ({session.degradedFields.length})
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {session.degradedFields.map((f) => (
              <li key={f} className="font-telemetry">{f}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
