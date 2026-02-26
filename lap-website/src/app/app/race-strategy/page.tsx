'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface StrategyRow {
  id: number;
  name: string;
  track_name: string;
  race_laps: number;
  pit_stops: number;
  total_time: number | null;
  status: 'draft' | 'active' | 'completed';
  created_at: string;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toFixed(1).padStart(4, '0')}`;
}

const statusColors: Record<string, string> = {
  draft: 'text-steel',
  active: 'text-acid-green',
  completed: 'text-marshal-yellow',
};

export default function RaceStrategyListPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['race-strategies'],
    queryFn: () => api.get<{ strategies: StrategyRow[] }>('/race-strategy'),
  });

  const strategies = data?.strategies ?? [];

  return (
    <div>
      <PageHeader
        title="Race Strategy"
        subtitle="Optimise pit stops, tyre compounds, and fuel load"
        actions={
          <Link
            href="/app/race-strategy/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            + New Strategy
          </Link>
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            { key: 'name', header: 'Strategy', sortable: true },
            { key: 'track_name', header: 'Track', sortable: true },
            {
              key: 'race_laps',
              header: 'Laps',
              sortable: true,
              className: 'font-telemetry text-right',
            },
            {
              key: 'pit_stops',
              header: 'Pit Stops',
              sortable: true,
              className: 'font-telemetry text-right',
            },
            {
              key: 'total_time',
              header: 'Est. Total',
              className: 'font-telemetry',
              render: (row: StrategyRow) => (
                <span className="text-acid-green">{formatTime(row.total_time)}</span>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              render: (row: StrategyRow) => (
                <span
                  className={`font-telemetry text-xs uppercase ${statusColors[row.status] ?? 'text-steel'}`}
                >
                  {row.status}
                </span>
              ),
            },
            {
              key: 'created_at',
              header: 'Created',
              sortable: true,
              className: 'font-telemetry text-sm',
            },
          ]}
          data={strategies}
          keyField="id"
          onRowClick={(row) => router.push(`/app/race-strategy/${row.id}`)}
          emptyMessage="No strategies yet. Create your first race strategy."
        />
      )}
    </div>
  );
}
