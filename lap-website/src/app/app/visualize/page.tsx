'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

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

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const min = Math.floor(s / 60);
  const sec = s - min * 60;
  return min > 0 ? `${min}:${sec.toFixed(3).padStart(6, '0')}` : `${sec.toFixed(3)}s`;
}

export default function VisualizeLandingPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['sessions', 'recent'],
    queryFn: () => api.get<{ sessions: SessionRow[] }>('/sessions/recent?limit=50'),
  });

  const sessions = data?.sessions ?? [];

  return (
    <div>
      <PageHeader
        title="Visualization"
        subtitle="Select a session to open the telemetry visualization tool"
      />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <p className="font-telemetry text-4xl text-steel/30 mb-4">◆</p>
          <h2 className="font-body text-chalk text-lg mb-2">No sessions yet</h2>
          <p className="text-steel font-body text-sm mb-6">
            Upload and analyze a session first, then come back here to visualize GPS traces, speed profiles, and GG diagrams.
          </p>
          <Link
            href="/app/analyze"
            className="inline-block px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded hover:bg-acid-green/80 transition-colors"
          >
            Analyze a Session
          </Link>
        </div>
      ) : (
        <DataTable
          columns={[
            {
              key: 'session_date',
              header: 'Date',
              sortable: true,
              className: 'font-telemetry text-sm',
            },
            { key: 'driver_name', header: 'Driver', sortable: true },
            { key: 'track_name', header: 'Track', sortable: true },
            { key: 'session_type', header: 'Type', className: 'font-telemetry text-xs uppercase' },
            {
              key: 'n_laps',
              header: 'Laps',
              className: 'font-telemetry text-center',
            },
            {
              key: 'best_lap_time_s',
              header: 'Best Lap',
              className: 'font-telemetry',
              render: (row: SessionRow) => (
                <span className="text-acid-green">{formatTime(row.best_lap_time_s)}</span>
              ),
            },
            {
              key: 'total_score',
              header: 'Score',
              className: 'font-telemetry',
              render: (row: SessionRow) => (
                <span>
                  {row.total_score != null ? `${row.total_score.toFixed(0)}` : '—'}
                  {row.grade ? ` (${row.grade})` : ''}
                </span>
              ),
            },
            {
              key: 'actions',
              header: '',
              render: (row: SessionRow) => (
                <Link
                  href={`/app/visualize/${row.session_id}`}
                  className="text-acid-green font-telemetry text-xs hover:underline"
                >
                  Visualize →
                </Link>
              ),
            },
          ]}
          data={sessions}
          keyField="session_id"
          emptyMessage="No sessions found."
        />
      )}
    </div>
  );
}
