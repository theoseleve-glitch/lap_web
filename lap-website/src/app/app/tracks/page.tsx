'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface TrackRow {
  track_id: string;
  track_name: string;
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
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'record'>('sessions');

  const { data, isLoading } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<{ tracks: TrackRow[] }>('/tracks'),
  });

  const tracks = data?.tracks ?? [];

  const filtered = useMemo(() => {
    let list = tracks;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((t) => t.track_name.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return a.track_name.localeCompare(b.track_name);
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
      <PageHeader title="Tracks" subtitle={`${tracks.length} track${tracks.length !== 1 ? 's' : ''}`} />

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

      {/* ── Loading ─────────────────────────────────────── */}
      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
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
            <button
              type="button"
              key={track.track_id}
              onClick={() => router.push(`/app/tracks/${track.track_id}`)}
              className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                hover:border-acid-green/40 transition-all"
            >
              {/* Track name */}
              <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                {track.track_name}
              </h3>

              {/* Meta row */}
              <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                <span>{fmtLength(track.lap_length_m)}</span>
                <span className="text-steel/20">|</span>
                <span>{track.session_count ?? 0} session{(track.session_count ?? 0) !== 1 ? 's' : ''}</span>
                {track.lap_count != null && track.lap_count > 0 && (
                  <>
                    <span className="text-steel/20">|</span>
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
                    <span className="text-steel/40 font-telemetry text-[10px]">
                      {track.start_lat.toFixed(4)}, {track.start_lon.toFixed(4)}
                    </span>
                  </div>
                )}
              </div>

              {/* Arrow hint */}
              <div className="mt-3 text-right">
                <span className="text-steel/30 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                  View details →
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
