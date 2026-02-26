'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface KartRow {
  id: number;
  name: string;
  number: string | null;
  chassis: string | null;
  engine: string | null;
  sessions_count: number;
  notes: string | null;
}

export default function KartsPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['karts'],
    queryFn: () => api.get<{ karts: KartRow[] }>('/karts'),
  });

  const karts = data?.karts ?? [];

  return (
    <div>
      <PageHeader
        title="Karts"
        subtitle={`${karts.length} kart${karts.length !== 1 ? 's' : ''}`}
        actions={
          <Link
            href="/app/karts/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            + New Kart
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
            {
              key: 'name',
              header: 'Name / Number',
              sortable: true,
              render: (row: KartRow) => (
                <span className="font-body">
                  {row.name}
                  {row.number && (
                    <span className="ml-2 text-steel font-telemetry text-xs">#{row.number}</span>
                  )}
                </span>
              ),
            },
            {
              key: 'chassis',
              header: 'Chassis',
              sortable: true,
              render: (row: KartRow) => <span>{row.chassis ?? '—'}</span>,
            },
            {
              key: 'engine',
              header: 'Engine',
              sortable: true,
              render: (row: KartRow) => <span>{row.engine ?? '—'}</span>,
            },
            {
              key: 'sessions_count',
              header: 'Sessions',
              sortable: true,
              className: 'font-telemetry text-right',
            },
            {
              key: 'notes',
              header: 'Notes',
              render: (row: KartRow) => (
                <span className="text-steel truncate max-w-xs block">{row.notes ?? '—'}</span>
              ),
            },
          ]}
          data={karts}
          keyField="id"
          onRowClick={(row) => router.push(`/app/karts/${row.id}`)}
          emptyMessage="No karts found. Add your first kart to get started."
        />
      )}
    </div>
  );
}
