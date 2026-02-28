'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';
import { Sparkline } from '@/components/app/charts';

interface SessionRow {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
}

interface DashboardStats {
  total_sessions: number;
  pb_time: number | null;
  avg_score: number | null;
  total_drivers: number;
  recent_scores: number[];
  recent_times: number[];
  recent_sessions: SessionRow[];
}

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function DashboardPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: () => api.get<DashboardStats>('/dashboard/stats'),
  });

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Dashboard" subtitle="Your telemetry overview" />
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  const stats = data ?? {
    total_sessions: 0,
    pb_time: null,
    avg_score: null,
    total_drivers: 0,
    recent_scores: [],
    recent_times: [],
    recent_sessions: [],
  };

  const sessionColumns = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      className: 'font-telemetry',
    },
    {
      key: 'track_name',
      header: 'Track',
      sortable: true,
      className: 'font-body',
    },
    {
      key: 'driver_name',
      header: 'Driver',
      sortable: true,
      className: 'font-body',
    },
    {
      key: 'laps',
      header: 'Laps',
      sortable: true,
      className: 'font-telemetry w-16',
    },
    {
      key: 'best_time',
      header: 'Best Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-acid-green">{formatTime(row.best_time)}</span>
      ),
    },
    {
      key: 'score',
      header: 'Score',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className={row.score != null && row.score >= 75 ? 'text-acid-green' : 'text-chalk'}>
          {row.score != null ? row.score.toFixed(1) : '--'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      className: 'font-monument w-16',
      render: (row: SessionRow) => {
        if (!row.grade) return <span className="text-steel">--</span>;
        const g = row.grade.toUpperCase();
        const c = g.startsWith('A') ? 'text-acid-green' : g.startsWith('B') ? 'text-emerald-400' : g.startsWith('C') ? 'text-amber-400' : 'text-safety-red';
        return <span className={c}>{row.grade}</span>;
      },
    },
  ];

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Your telemetry overview" />

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Sessions" value={stats.total_sessions} />
        <StatCard
          label="Personal Best"
          value={formatTime(stats.pb_time)}
          trend={stats.pb_time != null ? 'up' : 'neutral'}
        />
        <StatCard
          label="Average Score"
          value={stats.avg_score != null ? stats.avg_score.toFixed(1) : '--'}
          unit="/100"
          trend={stats.avg_score != null && stats.avg_score >= 75 ? 'up' : 'neutral'}
        />
        <StatCard label="Total Drivers" value={stats.total_drivers} />
      </div>

      {/* Sparklines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Score Trend (Last 20)
          </p>
          {stats.recent_scores.length > 1 ? (
            <Sparkline data={stats.recent_scores} color="#B6FF2E" height={48} />
          ) : (
            <div className="h-12 flex items-center justify-center text-steel font-telemetry text-xs">
              Not enough data
            </div>
          )}
        </div>
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Lap Time Trend (Last 20)
          </p>
          {stats.recent_times.length > 1 ? (
            <Sparkline data={stats.recent_times} color="#FFD400" height={48} />
          ) : (
            <div className="h-12 flex items-center justify-center text-steel font-telemetry text-xs">
              Not enough data
            </div>
          )}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 mb-6">
        <Link
          href="/app/analyze"
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-acid-green text-carbon font-telemetry text-sm font-semibold rounded-lg hover:bg-acid-green/90 transition-colors"
        >
          + New Analysis
        </Link>
        <Link
          href="/app/sessions"
          className="inline-flex items-center gap-2 px-4 py-2.5 border border-steel/20 text-steel font-telemetry text-sm rounded-lg hover:text-chalk hover:border-steel/40 transition-colors"
        >
          View All Sessions
        </Link>
      </div>

      {/* Recent sessions table */}
      <div>
        <h2 className="font-body text-chalk text-lg mb-3">Recent Sessions</h2>
        <DataTable
          columns={sessionColumns}
          data={stats.recent_sessions}
          keyField="id"
          onRowClick={(row) => router.push(`/app/sessions/${row.id}`)}
          emptyMessage="No sessions recorded yet"
        />
      </div>
    </div>
  );
}
