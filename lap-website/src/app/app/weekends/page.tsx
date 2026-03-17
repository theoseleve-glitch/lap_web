'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* ── Types ──────────────────────────────────────────────── */

interface WeekendRow {
  id: number;
  name: string;
  track_name: string;
  start_date: string;
  end_date: string | null;
  sessions_count: number;
  notes?: string | null;
}

/* ── Helpers ────────────────────────────────────────────── */

function formatDateRange(start: string, end: string | null): string {
  if (!end || end === start) return formatDate(start);
  return `${formatDate(start)} – ${formatDate(end)}`;
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function daysSpan(start: string, end: string | null): number {
  if (!end || end === start) return 1;
  const s = new Date(start + 'T00:00:00');
  const e = new Date(end + 'T00:00:00');
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / 86_400_000) + 1);
}

function isUpcoming(start: string): boolean {
  return new Date(start + 'T00:00:00') > new Date();
}

function isPast(end: string | null, start: string): boolean {
  const d = end ?? start;
  return new Date(d + 'T23:59:59') < new Date();
}

/* ── Page ───────────────────────────────────────────────── */

export default function WeekendsPage() {

  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'date' | 'name' | 'sessions'>('date');
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['weekends'],
    queryFn: () => api.get<{ weekends: WeekendRow[] }>('/weekends'),
  });

  const weekends = data?.weekends ?? [];

  const deleteMutation = useMutation({
    mutationFn: (weekendId: number) => api.delete(`/weekends/${weekendId}`),
    onMutate: async (weekendId) => {
      setDeleteError(null);
      await queryClient.cancelQueries({ queryKey: ['weekends'] });
      const prev = queryClient.getQueryData<{ weekends: WeekendRow[] }>(['weekends']);
      if (prev) {
        queryClient.setQueryData<{ weekends: WeekendRow[] }>(['weekends'], {
          ...prev,
          weekends: prev.weekends.filter((w) => w.id !== weekendId),
        });
      }
      setConfirmDelete(null);
      return { prev };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['weekends'] });
    },
    onError: (_err, _id, context) => {
      if (context?.prev) queryClient.setQueryData(['weekends'], context.prev);
      setDeleteError(_err instanceof Error ? _err.message : 'Failed to delete weekend');
    },
  });

  const filtered = useMemo(() => {
    let list = weekends;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (w) =>
          w.name?.toLowerCase().includes(q) ||
          (w.track_name ?? '').toLowerCase().includes(q),
      );
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return (a.name ?? '').localeCompare(b.name ?? '');
      if (sort === 'sessions') return (b.sessions_count ?? 0) - (a.sessions_count ?? 0);
      if (sort === 'date') return (b.start_date ?? '').localeCompare(a.start_date ?? '');
      return 0;
    });
    return list;
  }, [weekends, search, sort]);

  // Aggregates
  const totalSessions = weekends.reduce((s, w) => s + (w.sessions_count ?? 0), 0);
  const totalDays = weekends.reduce((s, w) => s + daysSpan(w.start_date, w.end_date), 0);
  const upcomingCount = weekends.filter((w) => isUpcoming(w.start_date)).length;
  const uniqueTracks = new Set(weekends.map((w) => w.track_name)).size;

  return (
    <div>
      <PageIntro
        title="Weekends"
        subtitle={`${weekends.length} weekend${weekends.length !== 1 ? 's' : ''}`}
        actions={
          <Link
            href="/app/weekends/new"
            className="px-4 py-2 bg-pit-orange text-white font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            + New Weekend
          </Link>
        }
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Weekends" value={weekends.length} />
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Track Days" value={totalDays} />
        <StatCard label={upcomingCount > 0 ? 'Upcoming' : 'Unique Tracks'} value={upcomingCount > 0 ? upcomingCount : uniqueTracks} />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search weekends, tracks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'date' | 'name' | 'sessions')}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="date">Most Recent</option>
          <option value="name">Alphabetical</option>
          <option value="sessions">Most Sessions</option>
        </select>
      </div>

      {/* ── Delete Error ──────────────────────────────── */}
      {deleteError && (
        <div className="flex items-center justify-between bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2 mb-4">
          <p className="text-safety-red font-telemetry text-xs">{deleteError}</p>
          <button type="button" onClick={() => setDeleteError(null)} className="text-safety-red/60 hover:text-safety-red text-xs ml-3">dismiss</button>
        </div>
      )}

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load weekends." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No weekends match &quot;{search}&quot;</p>
              <button type="button" onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline">
                Clear search
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">📅</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No weekends yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Create a weekend to group related sessions together — perfect for multi-day
                events, championships, or test days.
              </p>
              <Link
                href="/app/weekends/new"
                className="inline-block mt-4 px-6 py-2.5 bg-pit-orange text-white font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
              >
                Create First Weekend
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((weekend) => {
            const upcoming = isUpcoming(weekend.start_date);
            const past = isPast(weekend.end_date, weekend.start_date);
            const days = daysSpan(weekend.start_date, weekend.end_date);

            return (
              <Link
                key={weekend.id}
                href={`/app/weekends/${weekend.id}`}
                className={`group text-left bg-concrete rounded-lg border p-5
                  hover:border-acid-green/40 transition-all ${
                    upcoming
                      ? 'border-marshal-yellow/30'
                      : 'border-steel/20'
                  }`}
              >
                {/* Status + Name + delete */}
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                    {weekend.name}
                  </h3>
                  <div className="flex items-center gap-2 shrink-0">
                    {upcoming && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-telemetry uppercase bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30">
                        UPCOMING
                      </span>
                    )}
                    {past && !upcoming && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-telemetry uppercase bg-steel/10 text-steel/60">
                        PAST
                      </span>
                    )}
                    {confirmDelete === weekend.id ? (
                      <span className="inline-flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                        <button
                          type="button"
                          onClick={(e) => { e.preventDefault(); deleteMutation.mutate(weekend.id); }}
                          disabled={deleteMutation.isPending}
                          className="px-2 py-0.5 text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/40 rounded hover:bg-safety-red/30 transition-colors disabled:opacity-50"
                        >
                          {deleteMutation.isPending ? 'Deleting...' : 'Confirm'}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => { e.preventDefault(); setConfirmDelete(null); setDeleteError(null); }}
                          disabled={deleteMutation.isPending}
                          className="px-1.5 py-0.5 text-[10px] font-telemetry text-steel hover:text-chalk transition-colors disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); setConfirmDelete(weekend.id); }}
                        title="Delete weekend"
                        className="p-1 text-steel/40 hover:text-safety-red transition-colors opacity-0 group-hover:opacity-100"
                      >
                        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>

                {/* Track */}
                <p className="text-steel font-body text-sm mt-1 truncate">
                  {weekend.track_name}
                </p>

                {/* Date range */}
                <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                  <span>{formatDateRange(weekend.start_date, weekend.end_date)}</span>
                  {days > 1 && (
                    <>
                      <span className="text-steel/60">|</span>
                      <span>{days} days</span>
                    </>
                  )}
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-3 mt-3">
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">SESSIONS</span>
                    <span className="text-chalk font-telemetry text-sm">{weekend.sessions_count ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-steel/60 text-[10px] font-telemetry block">DAYS</span>
                    <span className="text-chalk font-telemetry text-sm">{days}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-steel/60 text-[10px] font-telemetry block">AVG/DAY</span>
                    <span className="text-chalk font-telemetry text-sm">
                      {days > 0 ? ((weekend.sessions_count ?? 0) / days).toFixed(1) : '—'}
                    </span>
                  </div>
                </div>

                {/* Notes preview */}
                {weekend.notes && (
                  <p className="text-steel/50 font-body text-xs mt-2 truncate">
                    {weekend.notes}
                  </p>
                )}

                <div className="mt-3 text-right">
                  <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                    View weekend →
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
