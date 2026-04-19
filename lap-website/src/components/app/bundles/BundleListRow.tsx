'use client';

import Link from 'next/link';
import type { BundleOverview } from '@/types/bundles';
import { SupportLevelBadge } from './SupportLevelBadge';

function shortDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

interface Props {
  bundle: BundleOverview;
}

export function BundleListRow({ bundle }: Props) {
  const statusColor = bundle.status === 'accepted'
    ? 'bg-acid-green/10 text-acid-green border-acid-green/30'
    : 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/30';
  const statusLabel = bundle.status === 'accepted' ? 'Ready' : 'Incomplete';

  return (
    <Link
      href={`/app/bundles/${bundle.bundle_id}`}
      className="flex items-center gap-4 px-4 py-3 rounded-lg border border-steel/5 bg-concrete hover:border-steel/20 transition-colors group"
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-monument text-chalk truncate group-hover:text-gold transition-colors">
          {bundle.track_name}
        </p>
        <p className="text-xs font-telemetry text-steel">
          {bundle.vehicle_name} &middot; {bundle.sim.toUpperCase()} &middot; {bundle.lap_count} laps
        </p>
      </div>

      <div className="hidden sm:block text-xs font-telemetry text-steel whitespace-nowrap">
        {shortDate(bundle.started_at)}
      </div>

      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-telemetry ${statusColor}`}>
        {statusLabel}
      </span>

      {bundle.latest_run_id && (
        <SupportLevelBadge tier={null} size="sm" />
      )}
    </Link>
  );
}
