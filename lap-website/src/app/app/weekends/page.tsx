'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface WeekendRow {
  id: number;
  name: string;
  track_name: string;
  start_date: string;
  end_date: string | null;
  sessions_count: number;
}

function formatDateRange(start: string, end: string | null): string {
  if (!end || end === start) return start;
  return `${start} – ${end}`;
}

export default function WeekendsPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['weekends'],
    queryFn: () => api.get<{ weekends: WeekendRow[] }>('/weekends'),
  });

  const weekends = data?.weekends ?? [];

  return (
    <div>
      <PageHeader
        title="Weekends"
        subtitle={`${weekends.length} weekend${weekends.length !== 1 ? 's' : ''}`}
        actions={
          <Link
            href="/app/weekends/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            + New Weekend
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
            { key: 'name', header: 'Name', sortable: true },
            { key: 'track_name', header: 'Track', sortable: true },
            {
              key: 'start_date',
              header: 'Date Range',
              sortable: true,
              render: (row: WeekendRow) => (
                <span className="font-telemetry text-sm">
                  {formatDateRange(row.start_date, row.end_date)}
                </span>
              ),
            },
            {
              key: 'sessions_count',
              header: 'Sessions',
              sortable: true,
              className: 'font-telemetry text-right',
            },
          ]}
          data={weekends}
          keyField="id"
          onRowClick={(row) => router.push(`/app/weekends/${row.id}`)}
          emptyMessage="No weekends found. Create a weekend to group your sessions."
        />
      )}
    </div>
  );
}
