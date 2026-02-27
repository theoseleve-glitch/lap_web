'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface TrackRow {
  track_id: string;
  track_name: string;
  session_count?: number;
  best_time_s?: number | null;
  lap_length_m?: number | null;
  start_lat?: number | null;
  start_lon?: number | null;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function TracksPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<{ tracks: TrackRow[] }>('/tracks'),
  });

  const tracks = data?.tracks ?? [];

  return (
    <div>
      <PageHeader title="Tracks" subtitle={`${tracks.length} tracks`} />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            {
              key: 'track_name',
              header: 'Track',
              sortable: true,
              render: (row: TrackRow) => <span>{row.track_name}</span>,
            },
            {
              key: 'lap_length_m',
              header: 'Lap Length',
              sortable: true,
              className: 'font-telemetry',
              render: (row: TrackRow) => (
                <span>{typeof row.lap_length_m === 'number' && row.lap_length_m > 0 ? `${Math.round(row.lap_length_m)} m` : '—'}</span>
              ),
            },
            {
              key: 'session_count',
              header: 'Sessions',
              sortable: true,
              className: 'font-telemetry text-right',
              render: (row: TrackRow) => <span>{row.session_count ?? 0}</span>,
            },
            {
              key: 'best_time_s', header: 'Record', sortable: true, className: 'font-telemetry',
              render: (row: TrackRow) => <span className="text-acid-green">{formatTime(row.best_time_s ?? null)}</span>,
            },
          ]}
          data={tracks}
          keyField="track_id"
          onRowClick={(row) => router.push(`/app/tracks/${row.track_id}`)}
          emptyMessage="No tracks found"
        />
      )}
    </div>
  );
}
