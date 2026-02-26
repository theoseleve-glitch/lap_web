'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';

interface DriverDetail {
  id: number;
  name: string;
  sessions_count: number;
  best_score: number | null;
  avg_score: number | null;
  best_time: number | null;
  favorite_track: string | null;
}

interface SessionSummary {
  id: string;
  date: string;
  track_name: string;
  score: number | null;
  best_time: number | null;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function DriverDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: driver, isLoading } = useQuery({
    queryKey: ['driver', id],
    queryFn: () => api.get<DriverDetail>(`/drivers/${id}`),
  });

  const { data: sessionsData } = useQuery({
    queryKey: ['driver', id, 'sessions'],
    queryFn: () => api.get<{ sessions: SessionSummary[] }>(`/drivers/${id}/sessions`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!driver) return <div className="text-steel font-body">Driver not found</div>;

  const sessions = sessionsData?.sessions ?? [];

  return (
    <div>
      <PageHeader title={driver.name} subtitle={`${driver.sessions_count} sessions`} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Best Score" value={driver.best_score?.toFixed(1) ?? '—'} unit="/100" trend="up" />
        <StatCard label="Avg Score" value={driver.avg_score?.toFixed(1) ?? '—'} unit="/100" />
        <StatCard label="Best Time" value={formatTime(driver.best_time)} />
        <StatCard label="Favorite Track" value={driver.favorite_track ?? '—'} />
      </div>

      <div className="mb-6">
        <ChartPanel title="Progression" subtitle="Score trend over sessions">
          <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
            Chart renders in Phase 4
          </div>
        </ChartPanel>
      </div>

      {sessions.length > 0 && (
        <div>
          <h2 className="font-body text-chalk text-lg mb-3">Session History</h2>
          <DataTable
            columns={[
              { key: 'date', header: 'Date', sortable: true, className: 'font-telemetry' },
              { key: 'track_name', header: 'Track', sortable: true },
              {
                key: 'best_time', header: 'Best Time', className: 'font-telemetry',
                render: (row: SessionSummary) => <span className="text-acid-green">{formatTime(row.best_time)}</span>,
              },
              {
                key: 'score', header: 'Score', sortable: true, className: 'font-telemetry text-right',
                render: (row: SessionSummary) => <span>{row.score?.toFixed(1) ?? '—'}</span>,
              },
            ]}
            data={sessions}
            keyField="id"
          />
        </div>
      )}
    </div>
  );
}
