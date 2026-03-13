'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, QueryError, SkeletonTableRows } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface DataHealthStats {
  total_files: number;
  success_count: number;
  failed_count: number;
  success_rate: number;
  avg_process_time_s: number | null;
}

interface JobRow {
  id: string;
  file_name: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  duration_s: number | null;
  peak_rss_mb: number | null;
  throughput_mb_s: number | null;
  error_message: string | null;
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return 'text-acid-green bg-acid-green/10';
    case 'processing': return 'text-pit-orange bg-pit-orange/10';
    case 'failed': return 'text-safety-red bg-safety-red/10';
    case 'pending': return 'text-steel bg-steel/10';
    default: return 'text-steel bg-steel/10';
  }
}

function formatDuration(s: number | null): string {
  if (s == null) return '—';
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
}

export default function DataHealthPage() {
  const router = useRouter();

  const { data: statsData, isLoading: statsLoading } = useQuery({
    queryKey: ['data-health-stats'],
    queryFn: () => api.get<DataHealthStats>('/data-health/stats'),
    refetchInterval: 10000,
  });

  const { data: jobsData, isLoading: jobsLoading, error: jobsError, refetch: refetchJobs } = useQuery({
    queryKey: ['data-health-jobs'],
    queryFn: () => api.get<{ jobs: JobRow[] }>('/data-health/jobs'),
    refetchInterval: 5000,
  });

  const jobs = jobsData?.jobs ?? [];

  return (
    <div>
      <PageIntro
        title="Data Health"
        subtitle="Processing job status and file ingestion metrics"
        actions={
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            Refresh
          </button>
        }
      />

      {statsLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-concrete rounded-lg border border-steel/20 p-4 h-20 animate-pulse" />
          ))}
        </div>
      ) : statsData ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
          <StatCard label="Total Files" value={statsData.total_files} />
          <StatCard
            label="Success Rate"
            value={`${statsData.success_rate.toFixed(1)}%`}
            trend={
              statsData.success_rate >= 90 ? 'up' :
              statsData.success_rate >= 70 ? 'neutral' : 'down'
            }
          />
          <StatCard
            label="Avg Process Time"
            value={formatDuration(statsData.avg_process_time_s)}
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
          <StatCard label="Total Files" value="—" />
          <StatCard label="Success Rate" value="—" />
          <StatCard label="Avg Process Time" value="—" />
        </div>
      )}

      {statsData && (statsData.success_count > 0 || statsData.failed_count > 0) && (
        <div className="flex gap-4 mb-6">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-acid-green inline-block" />
            <span className="text-steel font-telemetry text-xs">{statsData.success_count} completed</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-safety-red inline-block" />
            <span className="text-steel font-telemetry text-xs">{statsData.failed_count} failed</span>
          </div>
        </div>
      )}

      <h2 className="font-monument text-lg text-chalk mb-3">Recent Processing Jobs</h2>

      {jobsLoading ? (
        <SkeletonTableRows rows={5} cols={5} />
      ) : jobsError ? (
        <QueryError message="Couldn't load processing jobs." onRetry={() => refetchJobs()} />
      ) : (
        <DataTable
          columns={[
            {
              key: 'file_name',
              header: 'File',
              sortable: true,
              render: (row: JobRow) => (
                <span className="font-body text-sm truncate max-w-xs block">{row.file_name}</span>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              sortable: true,
              render: (row: JobRow) => (
                <span className={`px-2 py-0.5 rounded text-xs font-telemetry uppercase tracking-wide ${statusColor(row.status)}`}>
                  {row.status}
                </span>
              ),
            },
            {
              key: 'started_at',
              header: 'Started',
              sortable: true,
              className: 'text-steel font-telemetry text-xs',
              render: (row: JobRow) => <span>{row.started_at ?? '—'}</span>,
            },
            {
              key: 'duration_s',
              header: 'Duration',
              sortable: true,
              className: 'font-telemetry text-right',
              render: (row: JobRow) => <span>{formatDuration(row.duration_s)}</span>,
            },
            {
              key: 'peak_rss_mb',
              header: 'Peak RAM',
              sortable: true,
              className: 'font-telemetry text-right',
              render: (row: JobRow) => (
                <span>{row.peak_rss_mb != null ? `${row.peak_rss_mb.toFixed(0)} MB` : '—'}</span>
              ),
            },
            {
              key: 'throughput_mb_s',
              header: 'Throughput',
              sortable: true,
              className: 'font-telemetry text-right',
              render: (row: JobRow) => (
                <span>{row.throughput_mb_s != null ? `${row.throughput_mb_s.toFixed(1)} MB/s` : '—'}</span>
              ),
            },
          ]}
          data={jobs}
          keyField="id"
          onRowClick={(row) => router.push(`/app/data-health/${row.id}`)}
          emptyMessage="No processing jobs found."
        />
      )}
    </div>
  );
}
