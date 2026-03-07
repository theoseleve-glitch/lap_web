'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, QueryError, SkeletonStatCards, SkeletonTableRows, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/** Inline Sparkline — lightweight SVG replacement for deleted chart component */
function Sparkline({ data, color = '#B6FF2E', height = 56 }: { data: number[]; color?: string; height?: number }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 200;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * w},${height - ((v - min) / range) * (height - 4) - 2}`).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="2" points={points} />
    </svg>
  );
}

interface SessionRow {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
}

interface DashboardStats {
  total_sessions: number;
  total_drivers: number;
  total_tracks: number;
  total_laps: number;
  pb_time: number | null;
  pb_session_id: string | null;
  avg_score: number | null;
  best_score: number | null;
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

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  practice:   { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Practice' },
  qualifying: { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Qualifying' },
  race:       { bg: 'bg-safety-red/10', text: 'text-safety-red', label: 'Race' },
  test:       { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Test' },
  endurance:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Endurance' },
};

function TypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-steel/60">—</span>;
  const style = TYPE_STYLES[type] ?? { bg: 'bg-steel/10', text: 'text-steel', label: type };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard', 'stats'],
    queryFn: () => api.get<DashboardStats>('/dashboard/stats'),
  });

  if (isLoading) {
    return (
      <div>
        <PageIntro title="Dashboard" subtitle="Your telemetry overview" />
        <SkeletonStatCards count={4} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <SkeletonBox className="h-3 w-24 mb-3" />
            <SkeletonBox className="h-24 w-full" />
          </div>
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <SkeletonBox className="h-3 w-24 mb-3" />
            <SkeletonBox className="h-24 w-full" />
          </div>
        </div>
        <SkeletonTableRows rows={5} cols={6} />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageIntro title="Dashboard" subtitle="Your telemetry overview" />
        <QueryError message="Couldn't load your dashboard data. The server may be temporarily unavailable." onRetry={() => refetch()} />
      </div>
    );
  }

  const stats = data ?? {
    total_sessions: 0,
    total_drivers: 0,
    total_tracks: 0,
    total_laps: 0,
    pb_time: null,
    pb_session_id: null,
    avg_score: null,
    best_score: null,
    recent_scores: [],
    recent_times: [],
    recent_sessions: [],
  };

  const isEmpty = stats.total_sessions === 0;

  const sessionColumns = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      className: 'font-telemetry whitespace-nowrap',
      render: (row: SessionRow) => {
        if (!row.date) return <span className="text-steel">--</span>;
        try {
          const d = new Date(row.date + 'T00:00:00');
          return <span>{d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}</span>;
        } catch {
          return <span>{row.date}</span>;
        }
      },
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
      key: 'session_type',
      header: 'Type',
      sortable: true,
      render: (row: SessionRow) => <TypeBadge type={row.session_type} />,
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
        <span className={row.score != null && row.score >= 75 ? 'text-acid-green' : row.score != null && row.score >= 50 ? 'text-amber-400' : 'text-chalk'}>
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

  /* ── Empty State: Welcome & Onboarding ── */
  if (isEmpty) {
    return (
      <div>
        <PageIntro title="Dashboard" subtitle="Your telemetry overview" />

        {/* Hero */}
        <div className="bg-concrete rounded-xl border border-steel/20 p-8 md:p-12 text-center mb-8">
          <div className="text-5xl mb-4">🏁</div>
          <h2 className="font-monument text-2xl text-chalk mb-3">Welcome to LAP Coach</h2>
          <p className="text-steel font-body max-w-lg mx-auto mb-6">
            Upload your first telemetry CSV and get instant analysis with lap times, corner coaching,
            G-force diagrams, and a performance score out of 100.
          </p>
          <Link
            href="/app/analyze"
            className="inline-flex items-center gap-2 px-6 py-3 bg-gold text-carbon font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors"
          >
            + Upload Your First Session
          </Link>
        </div>

        {/* How It Works */}
        <h3 className="font-body text-chalk text-lg mb-4">How It Works</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {[
            { step: '1', title: 'Upload CSV', desc: 'Export from RaceChrono, RaceBox, or any GPS logger and upload your file.' },
            { step: '2', title: 'Auto-Analysis', desc: 'Our 14-stage pipeline processes your data: GPS, laps, corners, scoring, coaching.' },
            { step: '3', title: 'Improve', desc: 'Review your score, follow coaching hints, and track progress across sessions.' },
          ].map((s) => (
            <div key={s.step} className="bg-concrete rounded-lg border border-steel/10 p-5">
              <div className="w-8 h-8 rounded-full bg-acid-green/20 text-acid-green font-monument text-sm flex items-center justify-center mb-3">
                {s.step}
              </div>
              <h4 className="text-chalk font-body font-semibold mb-1">{s.title}</h4>
              <p className="text-steel text-sm font-body">{s.desc}</p>
            </div>
          ))}
        </div>

        {/* Feature Cards */}
        <h3 className="font-body text-chalk text-lg mb-4">What You Get</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { icon: '📊', title: 'Scoring', desc: 'Pace, consistency, execution, robustness — scored out of 100' },
            { icon: '🔄', title: 'Corner Coaching', desc: 'Entry, apex, exit speed analysis per corner' },
            { icon: '📈', title: 'Progress Tracking', desc: 'Compare sessions and see improvement over time' },
            { icon: '🏆', title: 'Achievements', desc: 'Earn badges and track personal bests' },
          ].map((f) => (
            <div key={f.title} className="bg-concrete rounded-lg border border-steel/10 p-4 text-center">
              <div className="text-2xl mb-2">{f.icon}</div>
              <h4 className="text-chalk font-telemetry text-xs font-semibold mb-1">{f.title}</h4>
              <p className="text-steel text-[10px] font-body">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  /* ── Populated Dashboard ── */
  return (
    <div>
      <PageIntro title="Dashboard" subtitle="Your telemetry overview" />

      {/* 7 Stat Cards — 2 rows */}
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-3 mb-4">
        <StatCard label="Sessions" value={stats.total_sessions} />
        <StatCard label="Drivers" value={stats.total_drivers} />
        <StatCard label="Tracks" value={stats.total_tracks} />
        <StatCard label="Total Laps" value={stats.total_laps.toLocaleString()} />
        {stats.pb_session_id ? (
          <Link href={`/app/sessions/${stats.pb_session_id}`} className="block">
            <StatCard
              label="Personal Best"
              value={formatTime(stats.pb_time)}
              trend={stats.pb_time != null ? 'up' : 'neutral'}
            />
          </Link>
        ) : (
          <StatCard
            label="Personal Best"
            value={formatTime(stats.pb_time)}
            trend={stats.pb_time != null ? 'up' : 'neutral'}
          />
        )}
        <StatCard
          label="Best Score"
          value={stats.best_score != null ? stats.best_score.toFixed(1) : '--'}
          unit="/100"
          trend={stats.best_score != null && stats.best_score >= 80 ? 'up' : 'neutral'}
        />
        <StatCard
          label="Avg Score"
          value={stats.avg_score != null ? stats.avg_score.toFixed(1) : '--'}
          unit="/100"
          trend={stats.avg_score != null && stats.avg_score >= 75 ? 'up' : stats.avg_score != null && stats.avg_score >= 50 ? 'neutral' : 'neutral'}
        />
      </div>

      {/* Sparklines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-steel font-telemetry text-xs uppercase tracking-wider">
              Score Trend
            </p>
            <span className="text-steel/60 font-telemetry text-[10px]">Last 20 sessions</span>
          </div>
          {stats.recent_scores.length > 1 ? (
            <Sparkline data={stats.recent_scores} color="#B6FF2E" height={56} />
          ) : (
            <div className="h-14 flex items-center justify-center text-steel font-telemetry text-xs">
              Not enough data
            </div>
          )}
        </div>
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-steel font-telemetry text-xs uppercase tracking-wider">
              Lap Time Trend
            </p>
            <span className="text-steel/60 font-telemetry text-[10px]">Last 20 sessions</span>
          </div>
          {stats.recent_times.length > 1 ? (
            <Sparkline data={stats.recent_times} color="#FFD400" height={56} />
          ) : (
            <div className="h-14 flex items-center justify-center text-steel font-telemetry text-xs">
              Not enough data
            </div>
          )}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3 mb-6">
        <Link
          href="/app/analyze"
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-gold text-carbon font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors"
        >
          + New Analysis
        </Link>
        <Link
          href="/app/sessions"
          className="inline-flex items-center gap-2 px-4 py-2.5 border border-steel/20 text-steel font-telemetry text-sm rounded-lg hover:text-chalk hover:border-steel/40 transition-colors"
        >
          View All Sessions
        </Link>
        <Link
          href="/app/compare"
          className="inline-flex items-center gap-2 px-4 py-2.5 border border-steel/20 text-steel font-telemetry text-sm rounded-lg hover:text-chalk hover:border-steel/40 transition-colors"
        >
          Compare Sessions
        </Link>
      </div>

      {/* Recent Sessions Table */}
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
