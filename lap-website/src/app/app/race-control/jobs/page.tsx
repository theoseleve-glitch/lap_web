'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { MetricCard } from '@/components/admin/MetricCard';

export default function AdminJobsPage() {
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState('');

  const { data: jobs, isLoading } = useQuery({
    queryKey: ['admin-jobs', statusFilter],
    queryFn: () => adminApi.listJobs({ status: statusFilter || undefined }),
  });

  const { data: stats } = useQuery({
    queryKey: ['admin-job-stats'],
    queryFn: adminApi.jobStats,
    refetchInterval: 60000,
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Jobs</h1>

      {/* Stats */}
      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
          <MetricCard label="Total (24h)" value={stats.total} />
          <MetricCard label="Failed" value={stats.failed} status={stats.failed > 5 ? 'error' : 'ok'} />
          <MetricCard label="Queue Depth" value={stats.queue_depth} status={stats.queue_depth > 10 ? 'warning' : 'ok'} />
          <MetricCard label="P50 Duration" value={`${(stats.p50_duration ?? 0).toFixed(1)}s`} />
          <MetricCard label="P95 Duration" value={`${(stats.p95_duration ?? 0).toFixed(1)}s`} />
        </div>
      )}

      {/* Filter */}
      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        className="mb-4 rounded border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-chalk"
      >
        <option value="">All statuses</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
        <option value="running">Running</option>
        <option value="queued">Queued</option>
      </select>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'job_id', label: 'Job ID', render: (r) => String(r.job_id).slice(0, 8) },
            { key: 'file_name', label: 'File' },
            { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status as string} /> },
            { key: 'duration_s', label: 'Duration', render: (r) => r.duration_s ? `${Number(r.duration_s).toFixed(1)}s` : '-' },
            { key: 'created_at', label: 'Created', render: (r) => new Date(r.created_at as string).toLocaleString() },
          ]}
          data={jobs ?? []}
          onRowClick={(row) => router.push(`/app/race-control/jobs/${row.job_id}`)}
        />
      )}
    </div>
  );
}
