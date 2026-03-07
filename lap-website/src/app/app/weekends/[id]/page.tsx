'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, QueryError, SkeletonStatCards, SkeletonBox, SkeletonTableRows } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface WeekendDetail {
  id: number;
  name: string;
  track_name: string;
  track_id: number;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  session_count: number;
  sessions: SessionRow[];
  created_at: string;
}

interface SessionRow {
  id: string;
  date: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-pit-orange';
  return 'text-safety-red';
}

function formatDateRange(start: string, end: string | null): string {
  if (!end || end === start) return start;
  return `${start} – ${end}`;
}

export default function WeekendDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const { data: weekend, isLoading, error: weekendError, refetch } = useQuery({
    queryKey: ['weekend', id],
    queryFn: () => api.get<WeekendDetail>(`/weekends/${id}`),
  });

  const sessions: SessionRow[] = weekend?.sessions ?? [];

  const bestTime = sessions.length
    ? Math.min(...sessions.filter(s => s.best_time != null).map(s => s.best_time as number))
    : null;
  const avgScore = sessions.length
    ? Number((sessions.reduce((sum, s) => sum + (s.score ?? 0), 0) / sessions.length).toFixed(1))
    : null;

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-40 mb-2" />
          <SkeletonBox className="h-3 w-24" />
        </div>
        <SkeletonStatCards count={3} />
        <SkeletonTableRows rows={4} cols={5} />
      </div>
    );
  }

  if (weekendError) {
    return <QueryError message="Couldn't load weekend details." onRetry={() => refetch()} />;
  }

  if (!weekend) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Weekend not found</h2>
        <p className="text-steel font-body text-sm mb-4">This weekend may have been deleted or the link is invalid.</p>
        <Link href="/app/weekends" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to weekends
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageIntro
        title={weekend.name}
        subtitle={`${weekend.track_name} · ${formatDateRange(weekend.start_date, weekend.end_date)}`}
        actions={
          <Link
            href="/app/weekends"
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            ← All Weekends
          </Link>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Sessions" value={weekend.session_count} />
        <StatCard label="Best Time" value={formatTime(bestTime)} />
        <StatCard
          label="Avg Score"
          value={avgScore != null ? avgScore.toFixed(1) : '—'}
          trend={
            avgScore == null ? 'neutral' :
            avgScore >= 80 ? 'up' :
            avgScore >= 60 ? 'neutral' : 'down'
          }
        />
      </div>

      {weekend.notes && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
          <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-2">Notes</h2>
          <p className="text-chalk font-body text-sm">{weekend.notes}</p>
        </div>
      )}

      <h2 className="font-monument text-lg text-chalk mb-3">Sessions</h2>
      <DataTable
        columns={[
          { key: 'date', header: 'Date', sortable: true },
          { key: 'driver_name', header: 'Driver', sortable: true },
          {
            key: 'laps',
            header: 'Laps',
            sortable: true,
            className: 'font-telemetry text-right',
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
            className: 'font-telemetry text-right',
            render: (row: SessionRow) => (
              <span className={scoreColor(row.score)}>
                {row.score != null ? row.score.toFixed(1) : '—'}
                {row.grade && (
                  <span className="ml-1 text-xs opacity-70">{row.grade}</span>
                )}
              </span>
            ),
          },
        ]}
        data={sessions}
        keyField="id"
        onRowClick={(row) => router.push(`/app/sessions/${row.id}`)}
        emptyMessage="No sessions in this weekend yet."
      />
    </div>
  );
}
