'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface TrackRow {
  id: number;
  name: string;
  country: string;
  city: string;
  sessions_count: number;
  best_time: number | null;
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
            { key: 'name', header: 'Track', sortable: true },
            { key: 'country', header: 'Country', sortable: true },
            { key: 'city', header: 'City', sortable: true },
            { key: 'sessions_count', header: 'Sessions', sortable: true, className: 'font-telemetry text-right' },
            {
              key: 'best_time', header: 'Record', sortable: true, className: 'font-telemetry',
              render: (row: TrackRow) => <span className="text-acid-green">{formatTime(row.best_time)}</span>,
            },
          ]}
          data={tracks}
          keyField="id"
          onRowClick={(row) => router.push(`/app/tracks/${row.id}`)}
          emptyMessage="No tracks found"
        />
      )}
    </div>
  );
}
