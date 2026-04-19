'use client';

import Link from 'next/link';
import { useBundleList, mapSessionPresentation, mapSupportTier, mapRunLifecycle } from '@/lib/api/bundles';
import type { SessionPresentation } from '@/lib/api/bundles/types';
import { SupportTierBadge, ReadinessBadge, RunLifecycleBadge } from '@/components/app/bundles/v2/StatusBadge';
import { FilterBar, useFilters, type Filters } from '@/components/app/bundles/v2/FilterBar';

function shortDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function matchesFilters(s: SessionPresentation, f: Filters): boolean {
  if (f.readiness && s.readiness !== f.readiness) return false;
  if (f.lifecycle && s.runLifecycle !== f.lifecycle) return false;
  if (f.tier && s.supportTier !== f.tier) return false;
  if (f.sim && s.sim !== f.sim) return false;
  return true;
}

export default function BundlesListPage() {
  const { data, isLoading, error } = useBundleList();
  const { filters, setFilters } = useFilters();

  const sessions: SessionPresentation[] = (data?.bundles ?? []).map(mapSessionPresentation);
  const sims = [...new Set(sessions.map((s) => s.sim))];
  const filtered = filters
    ? sessions.filter((s) => matchesFilters(s, filters))
    : sessions;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-monument text-chalk">Session Analysis</h1>
        <Link
          href="/app/bundles/upload"
          className="bg-gold text-white font-telemetry text-sm px-4 py-2 rounded-lg hover:bg-gold/80 transition-colors"
        >
          Upload Session
        </Link>
      </div>

      {/* Filter bar */}
      {sessions.length > 0 && (
        <FilterBar sims={sims} filters={filters} onChange={setFilters} />
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 rounded-lg bg-concrete animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-safety-red/30 bg-safety-red/5 p-4">
          <p className="text-sm font-body text-safety-red">Failed to load sessions.</p>
        </div>
      )}

      {/* Empty */}
      {data && sessions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <p className="text-lg font-monument text-chalk mb-2">No sessions yet</p>
          <p className="text-sm font-body text-steel mb-6 max-w-sm">
            Upload your first session bundle to start analyzing track surface,
            grip levels, and racing strategy.
          </p>
          <Link
            href="/app/bundles/upload"
            className="bg-gold text-white font-telemetry text-sm px-5 py-2.5 rounded-lg hover:bg-gold/80 transition-colors"
          >
            Upload Session
          </Link>
        </div>
      )}

      {/* Filtered empty */}
      {sessions.length > 0 && filtered.length === 0 && (
        <p className="text-sm font-body text-steel py-8 text-center">
          No sessions match the current filters.
        </p>
      )}

      {/* List */}
      {filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((s) => (
            <Link
              key={s.bundleId}
              href={`/app/bundles/${s.bundleId}`}
              className="flex items-center gap-4 px-4 py-3 rounded-lg border border-steel/5 bg-concrete hover:border-steel/20 transition-colors group"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm font-monument text-chalk truncate group-hover:text-gold transition-colors">
                  {s.trackName ?? 'Unknown Track'}
                </p>
                <p className="text-xs font-telemetry text-steel">
                  {s.vehicleName ?? 'Unknown Vehicle'} &middot; {s.sim.toUpperCase()} &middot; {s.lapCount} laps
                </p>
              </div>
              <div className="hidden sm:block text-xs font-telemetry text-steel whitespace-nowrap">
                {shortDate(s.startedAt)}
              </div>
              <ReadinessBadge state={s.readiness} />
              <RunLifecycleBadge state={s.runLifecycle} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
