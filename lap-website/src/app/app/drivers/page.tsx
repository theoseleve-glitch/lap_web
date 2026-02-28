'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface DriverRow {
  driver_id: number;
  driver_name: string;
  session_count: number;
  personal_best_s: number | null;
  mean_score: number | null;
  has_profile: boolean;
  style_label: string | null;
  total_laps: number;
}

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
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'score'>('sessions');

  const { data, isLoading } = useQuery({
    queryKey: ['drivers'],
    queryFn: () => api.get<{ drivers: DriverRow[] }>('/drivers'),
  });

  const drivers = data?.drivers ?? [];

  const filtered = useMemo(() => {
    let list = drivers;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((d) => d.driver_name.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return a.driver_name.localeCompare(b.driver_name);
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
      <PageHeader title="Drivers" subtitle={`${drivers.length} driver${drivers.length !== 1 ? 's' : ''}`} />

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
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
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
              <div className="text-4xl mb-3">👤</div>
              <h3 className="font-monument text-lg text-chalk mb-2">No drivers yet</h3>
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
              <button
                key={driver.driver_id}
                onClick={() => router.push(`/app/drivers/${driver.driver_id}`)}
                className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                  hover:border-acid-green/40 transition-all"
              >
                {/* Name + style */}
                <div className="flex items-start justify-between">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors">
                    {driver.driver_name}
                  </h3>
                  {driver.style_label && (
                    <span className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${
                      STYLE_COLORS[driver.style_label] ?? 'bg-steel/10 text-steel'
                    }`}>
                      {driver.style_label}
                    </span>
                  )}
                </div>

                {/* Stats row */}
                <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                  <span>{driver.session_count} session{driver.session_count !== 1 ? 's' : ''}</span>
                  <span className="text-steel/20">|</span>
                  <span>{driver.total_laps} laps</span>
                  {driver.has_profile && (
                    <>
                      <span className="text-steel/20">|</span>
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
                  <span className="text-steel/30 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                    View profile →
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
