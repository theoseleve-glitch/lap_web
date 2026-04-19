'use client';

import type { BundleOverview } from '@/types/bundles';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatDuration(s: number): string {
  const min = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${min}m ${sec}s`;
}

interface Props {
  bundle: BundleOverview;
}

export function IntakeResultCard({ bundle }: Props) {
  const statusColor = bundle.status === 'accepted'
    ? 'bg-acid-green/10 text-acid-green border-acid-green/30'
    : 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/30';
  const statusLabel = bundle.status === 'accepted' ? 'Ready' : 'Incomplete';

  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-monument text-chalk">{bundle.track_name}</h3>
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-telemetry ${statusColor}`}>
          {statusLabel}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <div>
          <span className="font-body text-steel">Vehicle</span>
          <p className="font-telemetry text-chalk">{bundle.vehicle_name || bundle.vehicle_key}</p>
        </div>
        <div>
          <span className="font-body text-steel">Sim</span>
          <p className="font-telemetry text-chalk uppercase">{bundle.sim}</p>
        </div>
        <div>
          <span className="font-body text-steel">Session</span>
          <p className="font-telemetry text-chalk">{bundle.session_type}</p>
        </div>
        <div>
          <span className="font-body text-steel">Date</span>
          <p className="font-telemetry text-chalk">{formatDate(bundle.started_at)}</p>
        </div>
        <div>
          <span className="font-body text-steel">Laps</span>
          <p className="font-telemetry text-chalk">{bundle.lap_count}</p>
        </div>
        <div>
          <span className="font-body text-steel">Duration</span>
          <p className="font-telemetry text-chalk">{formatDuration(bundle.duration_s)}</p>
        </div>
      </div>
    </div>
  );
}
