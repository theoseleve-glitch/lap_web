'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, QueryError, SkeletonStatCards, SkeletonTableRows, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { DriverAchievements } from '@/components/app/DriverAchievements';
import { ActivationChecklist } from '@/components/app/ActivationChecklist';
import { NpsSurvey } from '@/components/app/NpsSurvey';
import { QuotaIndicator } from '@/components/app/plan';
import XPProgressBar from '@/components/app/gamification/XPProgressBar';
import { StreakTracker } from '@/components/app/gamification';
import { ChallengeCard } from '@/components/app/gamification';

/**
 * ScoreTrendChart — a per-session bar readout (telemetry/stint style).
 *
 * Replaces the old stretched-SVG sparkline (which distorted under
 * preserveAspectRatio="none"). CSS bars stay crisp at any width: each session
 * is a bar whose height tracks its score within the window, brightness ramps
 * with the score, the latest session glows, and a dashed line marks the
 * average. Pure CSS — no distortion, no chart dependency.
 */
function ScoreTrendChart({ data, height = 72 }: { data: number[]; height?: number }) {
  if (data.length < 2) return null;
  const lo = Math.min(...data);
  const hi = Math.max(...data);
  const range = hi - lo || 1;
  const avg = data.reduce((a, b) => a + b, 0) / data.length;
  const FLOOR = 0.16; // keep even the lowest bar visible
  const fill = (v: number) => FLOOR + (1 - FLOOR) * ((v - lo) / range);
  const avgPct = fill(avg) * 100;
  const lastIdx = data.length - 1;
  return (
    <div className="relative w-full" style={{ height }} aria-label="Score per session">
      {/* average reference line */}
      <div
        className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-steel/25 z-10"
        style={{ bottom: `${avgPct}%` }}
      >
        <span className="absolute -top-3.5 right-0 text-[9px] font-telemetry text-steel/45">
          avg {avg.toFixed(1)}
        </span>
      </div>
      {/* bars */}
      <div className="absolute inset-0 flex items-end gap-[3px]">
        {data.map((v, i) => {
          const t = (v - lo) / range; // 0..1 within window
          const isLast = i === lastIdx;
          const op = (0.4 + 0.6 * t).toFixed(2);
          return (
            <div key={i} className="group relative flex flex-1 items-end" style={{ height: '100%' }}>
              <div
                className="w-full rounded-t-[2px] transition-[height] duration-300"
                style={{
                  height: `${(fill(v) * 100).toFixed(1)}%`,
                  background: isLast
                    ? 'linear-gradient(to top, rgba(182,255,46,0.85), #B6FF2E)'
                    : `linear-gradient(to top, rgba(182,255,46,${(+op * 0.45).toFixed(2)}), rgba(182,255,46,${op}))`,
                  boxShadow: isLast ? '0 0 10px rgba(182,255,46,0.55)' : 'none',
                }}
              />
              {/* hover tooltip */}
              <span className="pointer-events-none absolute -top-5 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded border border-steel/20 bg-asphalt px-1.5 py-0.5 text-[9px] font-telemetry text-chalk opacity-0 transition-opacity group-hover:opacity-100">
                #{i + 1} · {v.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
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
            className="inline-flex items-center gap-2 px-6 py-3 bg-gold text-white font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors"
          >
            + Upload Your First Session
          </Link>
        </div>

        {/* How It Works */}
        <h3 className="font-body text-chalk text-lg mb-4">How It Works</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 mb-8">
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

      {/* Plan quota — inline usage bar */}
      <div className="mb-4">
        <QuotaIndicator />
      </div>

      {/* 6 Stat Cards — 2 rows */}
      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3 mb-4">
        <StatCard label="Sessions" value={stats.total_sessions} />
        <StatCard label="Drivers" value={stats.total_drivers} />
        <StatCard label="Tracks" value={stats.total_tracks} />
        <StatCard label="Total Laps" value={stats.total_laps.toLocaleString()} />
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

      {/* ── Driver Progress & Challenges ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        {/* XP + Level progress */}
        <div className="lg:col-span-2">
          <XPProgressBar
            totalXp={stats.total_xp ?? 0}
            level={stats.level ?? 1}
            xpForCurrentLevel={stats.xp_for_current_level ?? 0}
            xpForNextLevel={stats.xp_for_next_level ?? 100}
          />
        </div>
        {/* Streak */}
        {stats.current_streak != null && (
          <StreakTracker
            currentStreak={stats.current_streak ?? 0}
            longestStreak={stats.longest_streak ?? 0}
            daysActive={stats.days_active ?? [false, false, false, false, false, false, false]}
          />
        )}
      </div>

      {/* Active challenges (if any) */}
      {stats.challenges && stats.challenges.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
          {stats.challenges.slice(0, 3).map((ch: any) => (
            <ChallengeCard
              key={ch.id}
              title={ch.title}
              description={ch.description}
              progress={ch.progress}
              maxProgress={ch.max_progress}
              reward={ch.reward_xp}
              timeLeft={ch.time_left}
              difficulty={ch.difficulty}
              completed={ch.completed}
              onAction={() => {}}
            />
          ))}
        </div>
      )}

      {/* Last session quick-access */}
      {stats.recent_sessions.length > 0 && (() => {
        const last = stats.recent_sessions[0];
        return (
          <Link
            href={`/app/sessions/${last.id}`}
            className="flex items-center gap-4 mb-4 px-4 py-3 bg-concrete border border-steel/20 rounded-lg hover:border-acid-green/40 transition-colors group"
          >
            <span className="text-acid-green font-telemetry text-xs uppercase tracking-wider shrink-0">Last session</span>
            <span className="text-chalk text-sm font-body truncate">{last.track_name}</span>
            <span className="text-steel text-xs font-body">{last.driver_name}</span>
            {last.best_time != null && (
              <span className="text-gold font-telemetry text-sm ml-auto shrink-0">{formatTime(last.best_time)}</span>
            )}
            <span className="text-steel/40 group-hover:text-steel transition-colors shrink-0">&rsaquo;</span>
          </Link>
        );
      })()}

      {/* Activation checklist for new users */}
      {stats.total_sessions < 5 && <ActivationChecklist />}

      {/* Trends */}
      <div className="grid grid-cols-1 gap-4 mb-6">
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-steel font-telemetry text-xs uppercase tracking-wider">
              Score Trend
            </p>
            <span className="text-steel/60 font-telemetry text-[10px]">Last 20 sessions</span>
          </div>
          {stats.recent_scores.length > 1 ? (() => {
            const scores = stats.recent_scores;
            const last = scores[scores.length - 1];
            const prev = scores[scores.length - 2];
            const delta = last - prev;
            const lo = Math.min(...scores);
            const hi = Math.max(...scores);
            const deltaUp = delta > 0;
            const deltaFlat = delta === 0;
            const deltaColor = deltaFlat ? 'text-steel' : deltaUp ? 'text-acid-green' : 'text-safety-red';
            const deltaArrow = deltaFlat ? '→' : deltaUp ? '▲' : '▼';
            return (
              <div>
                <div className="flex items-end justify-between gap-3 mb-2">
                  <div className="flex items-baseline gap-2">
                    <span className="text-chalk font-telemetry text-xl leading-none">{last.toFixed(1)}</span>
                    <span
                      className={`font-telemetry text-xs ${deltaColor}`}
                      title={`Change vs previous session (${prev.toFixed(1)})`}
                    >
                      {deltaArrow} {deltaFlat ? '±0.0' : `${deltaUp ? '+' : ''}${delta.toFixed(1)}`}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 font-telemetry text-[10px] text-steel/70">
                    <span title="Lowest score in window">Min {lo.toFixed(1)}</span>
                    <span title="Highest score in window">Max {hi.toFixed(1)}</span>
                  </div>
                </div>
                <ScoreTrendChart data={scores} height={72} />
              </div>
            );
          })() : (
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
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-gold text-white font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors"
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

      {/* Achievements */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h2 className="font-monument text-sm text-chalk mb-3">Achievements</h2>
        <DriverAchievements />
      </div>

      {/* NPS Survey */}
      <NpsSurvey sessionCount={stats.total_sessions} />

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
