'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { ActionButton } from '@/components/admin/ActionButton';

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: job, isLoading } = useQuery({
    queryKey: ['admin-job', id],
    queryFn: () => adminApi.getJob(id),
  });

  if (isLoading) return <p className="text-steel">Loading...</p>;
  if (!job) return <p className="text-red-400">Job not found</p>;

  const canRetry = job.status === 'failed' || job.status === 'error';
  const canCancel = ['queued', 'running', 'processing'].includes(job.status);

  return (
    <div>
      <h1 className="mb-2 text-xl font-bold text-chalk">{job.file_name}</h1>
      <div className="mb-6 flex items-center gap-2">
        <StatusBadge status={job.status} />
        <span className="text-xs text-steel">{job.job_id}</span>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Status" value={job.status} />
        <MetricCard label="Duration" value={job.duration_s ? `${Number(job.duration_s).toFixed(1)}s` : '-'} />
        <MetricCard label="Retries" value={job.retry_count ?? 0} />
        <MetricCard label="Created" value={new Date(job.created_at).toLocaleString()} />
      </div>

      {job.error_message && (
        <div className="mb-6 rounded-lg border border-red-500/20 bg-red-500/5 p-4">
          <p className="text-xs font-medium text-red-400">Error</p>
          <p className="mt-1 text-sm text-chalk/80 font-mono">{job.error_message}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3">
        {canRetry && (
          <ActionButton
            label="Retry"
            onConfirm={async (reason) => {
              await adminApi.retryJob(id, reason);
              queryClient.invalidateQueries({ queryKey: ['admin-job', id] });
            }}
          />
        )}
        {canCancel && (
          <ActionButton
            label="Cancel"
            variant="danger"
            onConfirm={async (reason) => {
              await adminApi.cancelJob(id, reason);
              queryClient.invalidateQueries({ queryKey: ['admin-job', id] });
            }}
          />
        )}
      </div>
    </div>
  );
}
