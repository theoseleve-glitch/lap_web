'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { canUseFeature, useEntitlementsStore } from '@/lib/entitlements-store';

/* ── Types ──────────────────────────────────────────────── */

interface RaceRow {
  race_id: number;
  race_name: string;
  track_name: string | null;
  team_name: string | null;
  race_duration_s: number;
  desired_stints: number;
  status: 'draft' | 'ready' | 'live' | 'finished';
  created_at: string;
}

/* ── Helpers ────────────────────────────────────────────── */

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h${m.toString().padStart(2, '0')}m`;
  return `${m}m`;
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

const STATUS_CONFIG: Record<string, { label: string; className: string; dotColor: string }> = {
  draft: {
    label: 'DRAFT',
    className: 'bg-steel/10 text-steel border-steel/30',
    dotColor: 'bg-steel',
  },
  ready: {
    label: 'READY',
    className: 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/30',
    dotColor: 'bg-marshal-yellow',
  },
  live: {
    label: 'LIVE',
    className: 'bg-acid-green/10 text-acid-green border-acid-green/30',
    dotColor: 'bg-gold animate-pulse',
  },
  finished: {
    label: 'FINISHED',
    className: 'bg-chalk/10 text-chalk border-chalk/30',
    dotColor: 'bg-chalk',
  },
};

/* ── Page ───────────────────────────────────────────────── */

export default function RaceStrategyListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const entitlements = useEntitlementsStore((s) => s.entitlements);
  const canComplex = canUseFeature('race_strategy_complex');
  const canFull = canUseFeature('race_strategy_full');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['race-strategy'],
    queryFn: () => api.get<{ races: RaceRow[] }>('/race-strategy/'),
  });

  const deleteMutation = useMutation({
    mutationFn: (raceId: number) => api.delete(`/race-strategy/${raceId}`),
    onMutate: async (raceId) => {
      setDeleteError('');
      await queryClient.cancelQueries({ queryKey: ['race-strategy'] });
      const prev = queryClient.getQueryData<{ races: RaceRow[] }>(['race-strategy']);
      if (prev) {
        queryClient.setQueryData<{ races: RaceRow[] }>(['race-strategy'], {
          ...prev,
          races: prev.races.filter((r) => r.race_id !== raceId),
        });
      }
      setConfirmDelete(null);
      return { prev };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['race-strategy'] });
    },
    onError: (_err, _raceId, context) => {
      if (_err instanceof Error && 'status' in _err && (_err as any).status === 404) {
        return;
      }
      if (context?.prev) {
        queryClient.setQueryData(['race-strategy'], context.prev);
      }
      const msg = _err instanceof Error ? _err.message : 'Delete failed';
      setDeleteError(msg);
      console.error('[race-delete]', _err);
    },
  });

  const races = data?.races ?? [];

  const filtered = useMemo(() => {
    let list = races;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (r) =>
          r.race_name.toLowerCase().includes(q) ||
          (r.track_name?.toLowerCase().includes(q) ?? false) ||
          (r.team_name?.toLowerCase().includes(q) ?? false),
      );
    }
    if (statusFilter !== 'all') {
      list = list.filter((r) => r.status === statusFilter);
    }
    // Live races first, then by creation date desc
    list = [...list].sort((a, b) => {
      if (a.status === 'live' && b.status !== 'live') return -1;
      if (b.status === 'live' && a.status !== 'live') return 1;
      return b.created_at.localeCompare(a.created_at);
    });
    return list;
  }, [races, search, statusFilter]);

  // Aggregates
  const liveCount = races.filter((r) => r.status === 'live').length;
  const finishedCount = races.filter((r) => r.status === 'finished').length;
  const totalRaceHours = races.reduce((s, r) => s + r.race_duration_s, 0) / 3600;

  const handleClick = (row: RaceRow) => {
    if (row.status === 'live') {
      router.push(`/app/race-strategy/${row.race_id}/live`);
    } else if (row.status === 'finished') {
      router.push(`/app/race-strategy/${row.race_id}/summary`);
    } else {
      router.push(`/app/race-strategy/${row.race_id}`);
    }
  };

  return (
    <div>
      <PageIntro
        title="Race Strategy"
        subtitle="Endurance race management — plan, optimize, and run"
        actions={
          <Link
            href="/app/race-strategy/new"
            className="inline-flex items-center gap-1 px-4 py-2 bg-gold text-white font-telemetry text-sm rounded hover:bg-gold/80 transition-colors"
          >
            + New Race
            {entitlements && !canFull && !canComplex && (
              <span className="text-[10px] opacity-60 ml-1" title="4h limit on Demo">4h max</span>
            )}
          </Link>
        }
      />

      {/* Quick-start guide — collapsible */}
      <details className="mb-4 bg-concrete border border-steel/20 rounded-lg">
        <summary className="px-5 py-3 cursor-pointer text-steel font-telemetry text-xs tracking-[0.08em] uppercase hover:text-chalk transition-colors select-none list-none flex items-center gap-2">
          <svg className="w-4 h-4 shrink-0 transition-transform [[open]>&]:rotate-90" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd"/></svg>
          How Race Strategy works
        </summary>
        <div className="px-5 pb-4 grid grid-cols-1 sm:grid-cols-4 gap-4 text-sm font-body">
          <div>
            <span className="text-steel/60 font-telemetry text-[10px] block mb-1">1. CREATE</span>
            <p className="text-steel">Set track, race duration, driver lineup, and target stints.</p>
          </div>
          <div>
            <span className="text-marshal-yellow font-telemetry text-[10px] block mb-1">2. PLAN</span>
            <p className="text-steel">Assign stints, set fuel windows, and preview the strategy timeline.</p>
          </div>
          <div>
            <span className="text-acid-green font-telemetry text-[10px] block mb-1">3. GO LIVE</span>
            <p className="text-steel">During the race, track lap times, adjust stints in real time, and monitor fuel.</p>
          </div>
          <div>
            <span className="text-chalk font-telemetry text-[10px] block mb-1">4. REVIEW</span>
            <p className="text-steel">After the race, view stint summaries, actual vs planned, and lap-by-lap data.</p>
          </div>
        </div>
      </details>

      {entitlements && !canFull && (
        <div className="mb-4">
          <UpgradeBanner
            feature={canComplex ? 'race_strategy_full' : 'race_strategy_complex'}
            context={
              canComplex
                ? 'Racer plan: races up to 24 hours. Upgrade for unlimited duration.'
                : 'Demo plan: races up to 4 hours. Upgrade for 24-hour races and advanced features.'
            }
          />
        </div>
      )}

      {deleteError && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 text-safety-red font-body text-sm flex items-center justify-between">
          <span>Delete failed: {deleteError}</span>
          <button type="button" onClick={() => setDeleteError('')} className="text-safety-red/60 hover:text-safety-red ml-4">{'\u2715'}</button>
        </div>
      )}

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Races" value={races.length} />
        <StatCard label="Live Now" value={liveCount} trend={liveCount > 0 ? 'up' : undefined} />
        <StatCard label="Completed" value={finishedCount} />
        <StatCard label="Race Hours" value={totalRaceHours > 0 ? totalRaceHours.toFixed(1) : '—'} unit="h" />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search races, tracks, teams..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold/50"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-gold focus:ring-1 focus:ring-gold/50"
        >
          <option value="all">All Status</option>
          <option value="draft">Draft</option>
          <option value="ready">Ready</option>
          <option value="live">Live</option>
          <option value="finished">Finished</option>
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={4} cols={2} />
      ) : error ? (
        <QueryError message="Couldn't load race strategies." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search || statusFilter !== 'all' ? (
            <>
              <p className="text-steel font-body text-sm">
                No races match your filters
              </p>
              <button
                type="button"
                onClick={() => { setSearch(''); setStatusFilter('all'); }}
                className="mt-3 text-gold font-telemetry text-xs hover:underline"
              >
                Clear filters
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">🏁</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No races yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Create your first endurance race strategy. Plan pit stops, manage driver stints,
                and optimize for the win.
              </p>
              <Link
                href="/app/race-strategy/new"
                className="inline-block mt-4 px-6 py-2.5 bg-gold text-white font-telemetry text-sm rounded hover:bg-gold/80 transition-colors"
              >
                Create First Race
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map((race) => {
            const cfg = STATUS_CONFIG[race.status] ?? STATUS_CONFIG.draft;

            return (
              <button
                key={race.race_id}
                onClick={() => handleClick(race)}
                className={`group text-left bg-concrete rounded-lg border p-5
                  hover:border-acid-green/40 transition-all ${
                    race.status === 'live'
                      ? 'border-acid-green/30'
                      : 'border-steel/20'
                  }`}
              >
                {/* Status + Name + Delete */}
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                    {race.race_name}
                  </h3>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-telemetry uppercase border ${cfg.className}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotColor}`} />
                      {cfg.label}
                    </span>
                    {race.status !== 'live' && (
                      confirmDelete === race.race_id ? (
                        <span
                          className="inline-flex items-center gap-1"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => deleteMutation.mutate(race.race_id)}
                            disabled={deleteMutation.isPending}
                            className="px-2 py-0.5 text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/40 rounded hover:bg-safety-red/30 transition-colors disabled:opacity-50"
                          >
                            {deleteMutation.isPending ? 'Deleting...' : 'Confirm'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDelete(null)}
                            className="px-1.5 py-0.5 text-[10px] font-telemetry text-steel hover:text-chalk transition-colors"
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setConfirmDelete(race.race_id); }}
                          title="Delete race"
                          className="p-1 text-steel/40 hover:text-safety-red transition-colors opacity-0 group-hover:opacity-100"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                          </svg>
                        </button>
                      )
                    )}
                  </div>
                </div>

                {/* Track + Team */}
                <div className="flex items-center gap-3 mt-1 text-steel font-body text-sm">
                  {race.track_name && <span>{race.track_name}</span>}
                  {race.track_name && race.team_name && <span className="text-steel/60">·</span>}
                  {race.team_name && <span>{race.team_name}</span>}
                  {!race.track_name && !race.team_name && <span className="text-steel/60">No track/team set</span>}
                </div>

                {/* Specs */}
                <div className="grid grid-cols-4 gap-3 mt-3">
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">DURATION</span>
                    <span className="text-chalk font-telemetry text-sm">{formatDuration(race.race_duration_s)}</span>
                  </div>
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">STINTS</span>
                    <span className="text-chalk font-telemetry text-sm">{race.desired_stints}</span>
                  </div>
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">CREATED</span>
                    <span className="text-steel font-telemetry text-xs">{formatDate(race.created_at)}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-steel/60 text-[10px] font-telemetry block">ACTION</span>
                    <span className="text-acid-green/60 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                      {race.status === 'live' ? 'Race Control →' :
                       race.status === 'finished' ? 'Summary →' :
                       'Configure →'}
                    </span>
                  </div>
                </div>

                {/* Live race accent bar */}
                {race.status === 'live' && (
                  <div className="mt-3 h-0.5 bg-acid-green/30 rounded-full overflow-hidden">
                    <div className="h-full w-1/3 bg-acid-green rounded-full animate-pulse" />
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
