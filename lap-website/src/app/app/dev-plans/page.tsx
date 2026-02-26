'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface DevPlanRow {
  id: number;
  title: string;
  status: 'draft' | 'in_progress' | 'completed' | 'archived';
  priority: 'low' | 'medium' | 'high' | 'critical';
  created_at: string;
  updated_at: string;
  progress_pct: number;
}

const statusColors: Record<string, string> = {
  draft: 'bg-steel/20 text-steel',
  in_progress: 'bg-acid-green/20 text-acid-green',
  completed: 'bg-marshal-yellow/20 text-marshal-yellow',
  archived: 'bg-steel/10 text-steel/50',
};

const priorityColors: Record<string, string> = {
  low: 'text-steel',
  medium: 'text-marshal-yellow',
  high: 'text-pit-orange',
  critical: 'text-safety-red',
};

export default function DevPlansPage() {
  const router = useRouter();
  const { data, isLoading } = useQuery({
    queryKey: ['dev-plans'],
    queryFn: () => api.get<{ plans: DevPlanRow[] }>('/dev-plans'),
  });

  const plans = data?.plans ?? [];

  return (
    <div>
      <PageHeader title="Development Plans" subtitle={`${plans.length} plan${plans.length !== 1 ? 's' : ''}`} />

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={[
            { key: 'title', header: 'Title', sortable: true },
            {
              key: 'status',
              header: 'Status',
              render: (row: DevPlanRow) => (
                <span
                  className={`px-2 py-0.5 rounded font-telemetry text-xs uppercase ${statusColors[row.status] ?? ''}`}
                >
                  {row.status.replace('_', ' ')}
                </span>
              ),
            },
            {
              key: 'priority',
              header: 'Priority',
              sortable: true,
              render: (row: DevPlanRow) => (
                <span className={`font-telemetry text-xs uppercase ${priorityColors[row.priority] ?? 'text-steel'}`}>
                  {row.priority}
                </span>
              ),
            },
            {
              key: 'progress_pct',
              header: 'Progress',
              className: 'w-32',
              render: (row: DevPlanRow) => (
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-steel/20 rounded-full h-1.5">
                    <div
                      className="bg-acid-green h-1.5 rounded-full"
                      style={{ width: `${row.progress_pct}%` }}
                    />
                  </div>
                  <span className="font-telemetry text-xs text-steel w-8 text-right">
                    {row.progress_pct}%
                  </span>
                </div>
              ),
            },
            {
              key: 'updated_at',
              header: 'Updated',
              sortable: true,
              className: 'font-telemetry text-sm',
            },
          ]}
          data={plans}
          keyField="id"
          onRowClick={(row) => router.push(`/app/dev-plans/${row.id}`)}
          emptyMessage="No development plans found."
        />
      )}
    </div>
  );
}
