'use client';

import Link from 'next/link';
import { useState, useMemo, lazy, Suspense } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

const DrivingAnalyzer = lazy(() => import('@/components/app/driving-analyzer/DrivingAnalyzer'));

/* ── Types ──────────────────────────────────────────────── */

interface SessionRow {
  session_id: string;
  driver_name: string;
  track_name: string;
  session_date: string;
  session_type: string;
  n_laps: number;
  best_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(s: number | null): string {
  if (s == null) return 'text-steel';
  if (s >= 80) return 'text-acid-green';
  if (s >= 60) return 'text-marshal-yellow';
  if (s >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

function scoreBorderColor(s: number | null): string {
  if (s == null) return 'border-steel/20';
  if (s >= 80) return 'border-acid-green/30';
  if (s >= 60) return 'border-marshal-yellow/30';
  if (s >= 40) return 'border-pit-orange/30';
  return 'border-safety-red/30';
}

function formatDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

const TYPE_LABELS: Record<string, string> = {
  practice: 'PRACTICE',
  qualifying: 'QUALI',
  race: 'RACE',
  test: 'TEST',
};

/* ── Page ───────────────────────────────────────────────── */

export default function VisualizeLandingPage() {

  const [search, setSearch] = useState('');
  const [analyzerSessionId, setAnalyzerSessionId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['sessions', 'recent'],
    queryFn: () => api.get<{ sessions: SessionRow[] }>('/sessions?limit=50&offset=0'),
  });

  const sessions = data?.sessions ?? [];

  const filtered = useMemo(() => {
    if (!search) return sessions;
    const q = search.toLowerCase();
    return sessions.filter(
      (s) =>
        s.driver_name.toLowerCase().includes(q) ||
        s.track_name.toLowerCase().includes(q) ||
        s.session_date.includes(q),
    );
  }, [sessions, search]);

  // Stats
  const totalLaps = sessions.reduce((s, r) => s + r.n_laps, 0);
  const scoredSessions = sessions.filter((s) => s.total_score != null);
  const avgScore = scoredSessions.length > 0
    ? scoredSessions.reduce((s, r) => s + r.total_score!, 0) / scoredSessions.length
    : null;

  return (
    <div>
      <PageIntro
        title="Visualization"
        subtitle="Select a session to open the telemetry visualization tool"
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Recent Sessions" value={sessions.length} />
        <StatCard label="Total Laps" value={totalLaps} />
        <StatCard label="Avg Score" value={avgScore?.toFixed(1) ?? '—'} unit="/100" />
        <StatCard label="Scored" value={scoredSessions.length} />
      </div>

      {/* ── Search ──────────────────────────────────────── */}
      <div className="mb-6">
        <input
          type="text"
          placeholder="Search by driver, track, date..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load sessions." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No sessions match &quot;{search}&quot;</p>
              <button type="button" onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline">
                Clear search
              </button>
            </>
          ) : (
            <>
              <p className="font-telemetry text-4xl text-steel/50 mb-4">◆</p>
              <h2 className="font-monument text-lg text-chalk mb-2">No sessions yet</h2>
              <p className="text-steel font-body text-sm mb-6 max-w-md mx-auto">
                Upload and analyze a session first, then come back here to visualize GPS traces,
                speed profiles, and GG diagrams.
              </p>
              <Link
                href="/app/analyze"
                className="inline-block px-6 py-2.5 bg-gold text-white font-telemetry text-sm rounded hover:bg-gold/80 transition-colors"
              >
                Analyze a Session
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((session) => (
            <Link
              key={session.session_id}
              href={`/app/visualize/${session.session_id}`}
              className={`group text-left bg-concrete rounded-lg border p-5
                hover:border-acid-green/40 transition-all ${scoreBorderColor(session.total_score)}`}
            >
              {/* Header: date + type */}
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-chalk font-telemetry text-sm">{formatDate(session.session_date)}</span>
                  <span className="text-steel/60 font-telemetry text-xs ml-2">{session.session_date}</span>
                </div>
                {session.session_type && (
                  <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-telemetry uppercase bg-steel/10 text-steel border border-steel/20">
                    {TYPE_LABELS[session.session_type] ?? session.session_type.toUpperCase()}
                  </span>
                )}
              </div>

              {/* Driver + Track */}
              <h3 className="font-monument text-base text-chalk group-hover:text-acid-green transition-colors mt-2 truncate">
                {session.driver_name}
              </h3>
              <p className="text-steel font-body text-sm truncate">{session.track_name}</p>

              {/* Metrics */}
              <div className="grid grid-cols-4 gap-2 mt-3">
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">LAPS</span>
                  <span className="text-chalk font-telemetry text-sm">{session.n_laps}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">BEST</span>
                  <span className="text-acid-green font-telemetry text-sm">{fmtTime(session.best_lap_time_s)}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">SCORE</span>
                  <span className={`font-telemetry text-sm ${scoreColor(session.total_score)}`}>
                    {session.total_score?.toFixed(0) ?? '—'}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-steel/60 text-[10px] font-telemetry block">GRADE</span>
                  <span className={`font-monument text-sm ${scoreColor(session.total_score)}`}>
                    {session.grade ?? '—'}
                  </span>
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between">
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setAnalyzerSessionId(session.session_id); }}
                  className="px-2.5 py-1 text-[10px] font-telemetry text-acid-green border border-acid-green/30 rounded hover:bg-gold/10 transition-colors"
                >
                  Analyze
                </button>
                <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                  Visualize →
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
      {analyzerSessionId && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 bg-asphalt/98 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
          </div>
        }>
          <DrivingAnalyzer
            sessionId={analyzerSessionId}
            onClose={() => setAnalyzerSessionId(null)}
          />
        </Suspense>
      )}
    </div>
  );
}
