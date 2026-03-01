'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable, QueryError, SkeletonTableRows } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface SessionRow {
  session_id: string;
  date: string;
  track_name: string;
  driver_name: string;
  lap_count: number;
  best_lap_time: number | null;
  mean_lap_time: number | null;
  total_score: number | null;
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
}

interface ListResponse {
  sessions: SessionRow[];
  total: number;
  limit: number;
  offset: number;
}

/* ── Helpers ────────────────────────────────────────────── */

function formatLapTime(seconds: number | null): string {
  if (seconds == null) return '—';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  practice:   { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Practice' },
  qualifying: { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Qualifying' },
  race:       { bg: 'bg-safety-red/10', text: 'text-safety-red', label: 'Race' },
  test:       { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Test' },
  endurance:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Endurance' },
};

const CONDITION_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  dry:    { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Dry' },
  wet:    { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Wet' },
  damp:   { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Damp' },
  mixed:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Mixed' },
  greasy: { bg: 'bg-pit-orange/10', text: 'text-pit-orange', label: 'Greasy' },
};

function TypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-steel/40">—</span>;
  const style = TYPE_STYLES[type] ?? { bg: 'bg-steel/10', text: 'text-steel', label: type };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function ConditionBadge({ condition }: { condition: string | null }) {
  if (!condition) return <span className="text-steel/40">—</span>;
  const style = CONDITION_STYLES[condition] ?? { bg: 'bg-steel/10', text: 'text-steel', label: condition };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function GradeBadge({ grade, score }: { grade: string | null; score: number | null }) {
  if (!grade) return <span className="text-steel/40">—</span>;
  const color = scoreColor(score);
  return (
    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-md border font-monument text-lg ${color} ${
      score != null && score >= 80 ? 'border-acid-green/30 bg-acid-green/5' :
      score != null && score >= 60 ? 'border-marshal-yellow/30 bg-marshal-yellow/5' :
      score != null && score >= 40 ? 'border-pit-orange/30 bg-pit-orange/5' :
      'border-safety-red/30 bg-safety-red/5'
    }`}>
      {grade}
    </span>
  );
}

/* ── Page Component ─────────────────────────────────────── */

const PER_PAGE = 25;

export default function SessionsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);

  const offset = (page - 1) * PER_PAGE;

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['sessions', 'list', page],
    queryFn: () => api.get<ListResponse>(`/sessions?limit=${PER_PAGE}&offset=${offset}`),
  });

  const sessions = data?.sessions ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const columns = [
    {
      key: 'date',
      header: 'Date',
      className: 'font-telemetry whitespace-nowrap',
    },
    {
      key: 'track_name',
      header: 'Track',
    },
    {
      key: 'driver_name',
      header: 'Driver',
    },
    {
      key: 'session_type',
      header: 'Type',
      render: (row: SessionRow) => <TypeBadge type={row.session_type} />,
    },
    {
      key: 'track_state',
      header: 'Condition',
      render: (row: SessionRow) => <ConditionBadge condition={row.track_state} />,
    },
    {
      key: 'lap_count',
      header: 'Laps',
      className: 'font-telemetry text-right',
    },
    {
      key: 'best_lap_time',
      header: 'Best Lap',
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-acid-green">{formatLapTime(row.best_lap_time)}</span>
      ),
    },
    {
      key: 'mean_lap_time',
      header: 'Mean Lap',
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-steel">{formatLapTime(row.mean_lap_time)}</span>
      ),
    },
    {
      key: 'total_score',
      header: 'Score',
      className: 'font-telemetry text-right',
      render: (row: SessionRow) => (
        <span className={scoreColor(row.total_score)}>
          {row.total_score != null ? row.total_score.toFixed(1) : '—'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      render: (row: SessionRow) => <GradeBadge grade={row.grade} score={row.total_score} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Sessions"
        subtitle={data ? `${total} session${total !== 1 ? 's' : ''}` : undefined}
        actions={
          <Link
            href="/app/sessions/upload"
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-acid-green text-carbon font-monument text-xs rounded-lg hover:bg-acid-green/90 transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" focusable="false">
              <line x1="7" y1="2" x2="7" y2="12" />
              <line x1="2" y1="7" x2="12" y2="7" />
            </svg>
            Upload Session
          </Link>
        }
      />

      {/* ── Stat Cards ──────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Sessions" value={total} />
        <StatCard label="Page" value={`${page} / ${totalPages}`} />
        <StatCard label="Showing" value={sessions.length} />
      </div>

      {/* ── Table ───────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonTableRows rows={8} cols={7} />
      ) : error ? (
        <QueryError message="Couldn't load sessions." onRetry={() => refetch()} />
      ) : sessions.length === 0 ? (
        /* Rich empty state */
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-5xl mb-4" aria-hidden="true">🏁</div>
          <h2 className="font-monument text-xl text-chalk mb-2">No sessions yet</h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto mb-6">
            This is where all your analyzed sessions will appear. Each session
            gets a score, grade, and detailed breakdown. Upload a RaceChrono or
            RaceBox CSV to get started.
          </p>
          <Link
            href="/app/sessions/upload"
            className="inline-flex items-center gap-2 px-6 py-3 bg-acid-green text-carbon font-monument text-sm rounded-lg hover:bg-acid-green/90 transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" focusable="false">
              <line x1="8" y1="2" x2="8" y2="14" />
              <line x1="2" y1="8" x2="14" y2="8" />
            </svg>
            Upload Session
          </Link>
        </div>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={sessions}
            keyField="session_id"
            onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
            emptyMessage="No sessions found"
            rowClassName={(row: SessionRow) => {
              if (row.total_score != null && row.total_score >= 80) return 'border-l-2 border-l-acid-green/30';
              if (row.total_score != null && row.total_score < 40) return 'border-l-2 border-l-safety-red/20';
              return '';
            }}
          />

          {/* ── Pagination ─────────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 px-1">
              <span className="text-steel/60 text-xs font-telemetry">
                Page {page} of {totalPages}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 rounded bg-concrete border border-steel/20 text-steel text-xs font-telemetry
                    hover:text-chalk hover:border-steel/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum: number;
                  if (totalPages <= 5) {
                    pageNum = i + 1;
                  } else if (page <= 3) {
                    pageNum = i + 1;
                  } else if (page >= totalPages - 2) {
                    pageNum = totalPages - 4 + i;
                  } else {
                    pageNum = page - 2 + i;
                  }
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`w-8 h-8 rounded text-xs font-telemetry transition-colors ${
                        pageNum === page
                          ? 'bg-pit-orange text-chalk'
                          : 'bg-concrete border border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 rounded bg-concrete border border-steel/20 text-steel text-xs font-telemetry
                    hover:text-chalk hover:border-steel/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
