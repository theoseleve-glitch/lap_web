'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';

interface TrackDetail {
  id: number;
  name: string;
  country: string;
  city: string;
  sessions_count: number;
  best_time: number | null;
  best_driver: string | null;
  avg_score: number | null;
}

interface LeaderboardEntry {
  rank: number;
  driver_name: string;
  best_time: number;
  date: string;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function TrackDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: track, isLoading } = useQuery({
    queryKey: ['track', id],
    queryFn: () => api.get<TrackDetail>(`/tracks/${id}`),
  });

  const { data: leaderboardData } = useQuery({
    queryKey: ['track', id, 'leaderboard'],
    queryFn: () => api.get<{ entries: LeaderboardEntry[] }>(`/tracks/${id}/leaderboard`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!track) return <div className="text-steel font-body">Track not found</div>;

  const leaderboard = leaderboardData?.entries ?? [];

  return (
    <div>
      <PageHeader title={track.name} subtitle={`${track.city}, ${track.country}`} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Track Record" value={formatTime(track.best_time)} trend="up" />
        <StatCard label="Record Holder" value={track.best_driver ?? '—'} />
        <StatCard label="Sessions" value={track.sessions_count} />
        <StatCard label="Avg Score" value={track.avg_score?.toFixed(1) ?? '—'} unit="/100" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ChartPanel title="Track Evolution" subtitle="Lap times over time">
          <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
            Chart renders in Phase 4
          </div>
        </ChartPanel>
        <ChartPanel title="Track Map" subtitle="GPS layout">
          <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
            Map renders in Phase 4
          </div>
        </ChartPanel>
      </div>

      {leaderboard.length > 0 && (
        <div>
          <h2 className="font-body text-chalk text-lg mb-3">Leaderboard</h2>
          <DataTable
            columns={[
              { key: 'rank', header: '#', className: 'font-telemetry w-12' },
              { key: 'driver_name', header: 'Driver', sortable: true },
              {
                key: 'best_time', header: 'Best Time', sortable: true, className: 'font-telemetry',
                render: (row: LeaderboardEntry) => <span className="text-acid-green">{formatTime(row.best_time)}</span>,
              },
              { key: 'date', header: 'Date', className: 'font-telemetry' },
            ]}
            data={leaderboard}
            keyField="rank"
          />
        </div>
      )}
    </div>
  );
}
