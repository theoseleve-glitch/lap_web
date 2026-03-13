'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { queryKeys } from '@/lib/query-keys';
import type { Driver } from '@/lib/api-types';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

/* ── Page ───────────────────────────────────────────────── */

export default function DriversPage() {

  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'score'>('sessions');
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const { data: drivers = [], isLoading, error, refetch } = useQuery({
    queryKey: queryKeys.drivers.all,
    queryFn: () => api.get<Driver[]>('/drivers'),
  });

  const deleteMutation = useMutation({
    mutationFn: (driverId: number) => api.delete(`/drivers/${driverId}`),
    onMutate: async (driverId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.drivers.all });
      const prev = queryClient.getQueryData<Driver[]>(queryKeys.drivers.all);
      queryClient.setQueryData<Driver[]>(queryKeys.drivers.all, (old) =>
        old ? old.filter((d) => d.id !== driverId) : [],
      );
      setConfirmDelete(null);
      return { prev };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.drivers.all });
    },
    onError: (_err, _id, context) => {
      if (context?.prev) queryClient.setQueryData(queryKeys.drivers.all, context.prev);
      const msg = _err instanceof Error ? _err.message : 'Delete failed';
      console.error('[driver-delete]', _err);
    },
  });

  const filtered = useMemo(() => {
    let list = drivers;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((d) => d.name.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'sessions') return (b.session_count ?? 0) - (a.session_count ?? 0);
      if (sort === 'score') return (b.mean_score ?? 0) - (a.mean_score ?? 0);
      return 0;
    });
    return list;
  }, [drivers, search, sort]);

  // Aggregates
  const totalSessions = drivers.reduce((s, d) => s + (d.session_count ?? 0), 0);
  const totalLaps = drivers.reduce((s, d) => s + (d.total_laps ?? 0), 0);
  const bestScore = drivers.reduce<number | null>((best, d) => {
    if (d.mean_score == null) return best;
    return best == null ? d.mean_score : Math.max(best, d.mean_score);
  }, null);

  return (
    <div>
      <PageIntro title="Drivers" subtitle={`${drivers.length} driver${drivers.length !== 1 ? 's' : ''}`} />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Drivers" value={drivers.length} />
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Total Laps" value={totalLaps} />
        <StatCard label="Top Avg Score" value={bestScore?.toFixed(1) ?? '—'} unit="/100" />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search drivers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'name' | 'sessions' | 'score')}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="sessions">Most Sessions</option>
          <option value="name">Alphabetical</option>
          <option value="score">Highest Score</option>
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load drivers." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No drivers match &quot;{search}&quot;</p>
              <button type="button" onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline">
                Clear search
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">👤</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No drivers yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Drivers are automatically detected from uploaded telemetry data.
                Upload a session CSV to get started.
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((driver) => {
            const tier = scoreColor(driver.mean_score);
            return (
              <Link
                key={driver.id}
                href={`/app/drivers/${driver.id}`}
                className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                  hover:border-acid-green/40 transition-all"
              >
                {/* Name + style + delete */}
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                    {driver.name}
                  </h3>
                  <div className="flex items-center gap-2 shrink-0">
                    {driver.style_label && (
                      <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${
                        STYLE_COLORS[driver.style_label] ?? 'bg-steel/10 text-steel'
                      }`}>
                        {driver.style_label}
                      </span>
                    )}
                    {confirmDelete === driver.id ? (
                      <span
                        className="inline-flex items-center gap-1"
                        onClick={(e) => e.preventDefault()}
                      >
                        <button
                          type="button"
                          onClick={(e) => { e.preventDefault(); deleteMutation.mutate(driver.id); }}
                          disabled={deleteMutation.isPending}
                          className="px-2 py-0.5 text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/40 rounded hover:bg-safety-red/30 transition-colors disabled:opacity-50"
                        >
                          {deleteMutation.isPending ? 'Deleting...' : 'Confirm'}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.preventDefault(); setConfirmDelete(null); }}
                          className="px-1.5 py-0.5 text-[10px] font-telemetry text-steel hover:text-chalk transition-colors"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); setConfirmDelete(driver.id); }}
                        title="Delete driver"
                        className="p-1 text-steel/40 hover:text-safety-red transition-colors opacity-0 group-hover:opacity-100"
                      >
                        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {/* Stats row */}
                <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                  <span>{driver.session_count} session{driver.session_count !== 1 ? 's' : ''}</span>
                  <span className="text-steel/60">|</span>
                  <span>{driver.total_laps} laps</span>
                  {driver.has_profile && (
                    <>
                      <span className="text-steel/60">|</span>
                      <span className="text-acid-green/60">Profile</span>
                    </>
                  )}
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-3 mt-3">
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">PB</span>
                    <span className="text-acid-green font-telemetry text-sm">
                      {fmtTime(driver.personal_best_s)}
                    </span>
                  </div>
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">AVG SCORE</span>
                    <span className={`font-telemetry text-sm ${tier}`}>
                      {driver.mean_score?.toFixed(1) ?? '—'}
                    </span>
                  </div>
                  <div className="text-right">
                    {/* Score bar */}
                    <span className="text-steel/60 text-[10px] font-telemetry block">LEVEL</span>
                    <div className="w-full h-1.5 bg-steel/10 rounded-full mt-1">
                      <div
                        className="h-full rounded-full bg-acid-green/60"
                        style={{ width: `${Math.min(100, (driver.mean_score ?? 0))}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="mt-3 text-right">
                  <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                    View profile →
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
