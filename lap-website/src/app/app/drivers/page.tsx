'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface DriverRow {
  id: number;
  name: string;
  sessions_count: number;
  best_score: number | null;
  avg_score: number | null;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  return 'text-safety-red';
}

export default function DriversPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['drivers'],
    queryFn: () => api.get<{ drivers: DriverRow[] }>('/drivers'),
  });

  const drivers = data?.drivers ?? [];

  return (
    <div>
      <PageHeader title="Drivers" subtitle={`${drivers.length} drivers`} />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            { key: 'name', header: 'Name', sortable: true },
            { key: 'sessions_count', header: 'Sessions', sortable: true, className: 'font-telemetry text-right' },
            {
              key: 'best_score', header: 'Best Score', sortable: true, className: 'font-telemetry text-right',
              render: (row: DriverRow) => <span className={scoreColor(row.best_score)}>{row.best_score?.toFixed(1) ?? '—'}</span>,
            },
            {
              key: 'avg_score', header: 'Avg Score', sortable: true, className: 'font-telemetry text-right',
              render: (row: DriverRow) => <span className={scoreColor(row.avg_score)}>{row.avg_score?.toFixed(1) ?? '—'}</span>,
            },
          ]}
          data={drivers}
          keyField="id"
          onRowClick={(row) => router.push(`/app/drivers/${row.id}`)}
          emptyMessage="No drivers found"
        />
      )}
    </div>
  );
}
