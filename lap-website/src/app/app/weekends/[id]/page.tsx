'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';

interface WeekendDetail {
  id: number;
  name: string;
  track_name: string;
  track_id: number;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  sessions_count: number;
  best_time: number | null;
  avg_score: number | null;
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

  const { data: weekend, isLoading: weekendLoading } = useQuery({
    queryKey: ['weekend', id],
    queryFn: () => api.get<WeekendDetail>(`/weekends/${id}`),
  });

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ['weekend-sessions', id],
    queryFn: () => api.get<{ sessions: SessionRow[] }>(`/weekends/${id}/sessions`),
  });

  const sessions = sessionsData?.sessions ?? [];
  const isLoading = weekendLoading || sessionsLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!weekend) {
    return (
      <div className="text-center py-16">
        <p className="text-steel font-body">Weekend not found.</p>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={weekend.name}
        subtitle={`${weekend.track_name} · ${formatDateRange(weekend.start_date, weekend.end_date)}`}
        actions={
          <button
            onClick={() => router.back()}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            ← Back
          </button>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Sessions" value={weekend.sessions_count} />
        <StatCard label="Best Time" value={formatTime(weekend.best_time)} />
        <StatCard
          label="Avg Score"
          value={weekend.avg_score != null ? weekend.avg_score.toFixed(1) : '—'}
          trend={
            weekend.avg_score == null ? 'neutral' :
            weekend.avg_score >= 80 ? 'up' :
            weekend.avg_score >= 60 ? 'neutral' : 'down'
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
