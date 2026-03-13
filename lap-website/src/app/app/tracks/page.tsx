'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* ── Types ──────────────────────────────────────────────── */

interface TrackRow {
  id: string;
  name: string;
  session_count: number;
  best_time_s: number | null;
  lap_length_m: number | null;
  lap_count: number | null;
  start_lat: number | null;
  start_lon: number | null;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function fmtLength(m: number | null): string {
  if (m == null || m <= 0) return '—';
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

/* ── Page ───────────────────────────────────────────────── */

export default function TracksPage() {

  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'record'>('sessions');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<TrackRow[]>('/tracks'),
  });

  const tracks = data ?? [];

  const deleteMutation = useMutation({
    mutationFn: (trackId: string) => api.delete(`/tracks/${trackId}`),
    onMutate: async (trackId) => {
      await queryClient.cancelQueries({ queryKey: ['tracks'] });
      const prev = queryClient.getQueryData<TrackRow[]>(['tracks']);
      queryClient.setQueryData<TrackRow[]>(['tracks'], (old) =>
        old ? old.filter((t) => t.id !== trackId) : [],
      );
      setConfirmDelete(null);
      return { prev };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tracks'] });
    },
    onError: (_err, _id, context) => {
      if (context?.prev) queryClient.setQueryData(['tracks'], context.prev);
      console.error('[track-delete]', _err);
    },
  });

  const filtered = useMemo(() => {
    let list = tracks;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((t) => (t.name ?? '').toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return (a.name ?? '').localeCompare(b.name ?? '');
      if (sort === 'sessions') return (b.session_count ?? 0) - (a.session_count ?? 0);
      if (sort === 'record') {
        if (a.best_time_s == null) return 1;
        if (b.best_time_s == null) return -1;
        return a.best_time_s - b.best_time_s;
      }
      return 0;
    });
    return list;
  }, [tracks, search, sort]);

  // Aggregate stats
  const totalSessions = tracks.reduce((s, t) => s + (t.session_count ?? 0), 0);
  const totalLaps = tracks.reduce((s, t) => s + (t.lap_count ?? 0), 0);
  const bestOverall = tracks.reduce<number | null>((best, t) => {
    if (t.best_time_s == null) return best;
    return best == null ? t.best_time_s : Math.min(best, t.best_time_s);
  }, null);

  return (
    <div>
      <PageIntro title="Tracks" subtitle={`${tracks.length} track${tracks.length !== 1 ? 's' : ''}`} />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Tracks" value={tracks.length} />
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Total Laps" value={totalLaps} />
        <StatCard label="Best Record" value={fmtTime(bestOverall)} />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search tracks..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'name' | 'sessions' | 'record')}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="sessions">Most Sessions</option>
          <option value="name">Alphabetical</option>
          <option value="record">Fastest Record</option>
        </select>
      </div>

      {/* ── Loading / Error / Content ─────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load tracks." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No tracks match &quot;{search}&quot;</p>
              <button
                type="button"
                onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline"
              >
                Clear search
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">🏁</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No tracks yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Tracks are automatically detected when you upload session data.
                Upload a telemetry CSV to get started.
              </p>
            </>
          )}
        </div>
      ) : (
        /* ── Track Cards Grid ────────────────────────────── */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((track) => (
            <Link
              key={track.id}
              href={`/app/tracks/${track.id}`}
              className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                hover:border-acid-green/40 transition-all"
            >
              {/* Track name + delete */}
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                  {track.name}
                </h3>
                <div className="flex items-center gap-2 shrink-0">
                  {confirmDelete === track.id ? (
                    <span className="inline-flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); deleteMutation.mutate(track.id); }}
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
                      onClick={(e) => { e.preventDefault(); setConfirmDelete(track.id); }}
                      title="Delete track"
                      className="p-1 text-steel/40 hover:text-safety-red transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {/* Meta row */}
              <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                <span>{fmtLength(track.lap_length_m)}</span>
                <span className="text-steel/60">|</span>
                <span>{track.session_count ?? 0} session{(track.session_count ?? 0) !== 1 ? 's' : ''}</span>
                {track.lap_count != null && track.lap_count > 0 && (
                  <>
                    <span className="text-steel/60">|</span>
                    <span>{track.lap_count} laps</span>
                  </>
                )}
              </div>

              {/* Record + Location */}
              <div className="flex items-center justify-between mt-3">
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">RECORD</span>
                  <span className="text-acid-green font-telemetry text-sm">
                    {fmtTime(track.best_time_s)}
                  </span>
                </div>
                {track.start_lat != null && track.start_lon != null && (
                  <div className="text-right">
                    <span className="text-steel/60 text-[10px] font-telemetry block">GPS</span>
                    <span className="text-steel/60 font-telemetry text-[10px]">
                      {track.start_lat.toFixed(4)}, {track.start_lon.toFixed(4)}
                    </span>
                  </div>
                )}
              </div>

              {/* Arrow hint */}
              <div className="mt-3 text-right">
                <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                  View details →
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
