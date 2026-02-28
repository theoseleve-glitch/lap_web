'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, QueryError, SkeletonTableRows } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface Job {
  job_id: string;
  file_name: string | null;
  status: string;
  stage_name: string | null;
  stage_index: number | null;
  stage_total: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

/* ── Helpers ────────────────────────────────────────────── */

const STATUS_CONFIG: Record<string, { label: string; className: string; dotClass: string }> = {
  queued: {
    label: 'Queued',
    className: 'bg-steel/10 text-steel border-steel/30',
    dotClass: 'bg-steel',
  },
  running: {
    label: 'Running',
    className: 'bg-blue-400/10 text-blue-400 border-blue-400/30',
    dotClass: 'bg-blue-400 animate-pulse',
  },
  processing: {
    label: 'Processing',
    className: 'bg-blue-400/10 text-blue-400 border-blue-400/30',
    dotClass: 'bg-blue-400 animate-pulse',
  },
  paused: {
    label: 'Paused',
    className: 'bg-marshal-yellow/10 text-marshal-yellow border-marshal-yellow/30',
    dotClass: 'bg-marshal-yellow',
  },
  completed: {
    label: 'Completed',
    className: 'bg-acid-green/10 text-acid-green border-acid-green/30',
    dotClass: 'bg-acid-green',
  },
  failed: {
    label: 'Failed',
    className: 'bg-safety-red/10 text-safety-red border-safety-red/30',
    dotClass: 'bg-safety-red',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-steel/10 text-steel/60 border-steel/20',
    dotClass: 'bg-steel/60',
  },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.queued;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] font-telemetry uppercase border ${cfg.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dotClass}`} />
      {cfg.label}
    </span>
  );
}

function ProgressBar({ job }: { job: Job }) {
  if (job.status !== 'running' && job.status !== 'processing' && job.status !== 'queued') return null;
  const index = job.stage_index ?? 0;
  const total = job.stage_total ?? 15;
  const pct = total > 0 ? Math.round((index / total) * 100) : 0;

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-steel/10">
        <div
          className="h-full rounded-full bg-acid-green transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] font-telemetry text-steel/60">{pct}%</span>
    </div>
  );
}

function timeAgo(isoDate: string | null): string {
  if (!isoDate) return '—';
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

/* ── Page ───────────────────────────────────────────────── */

export default function JobsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['jobs', 50],
    queryFn: () => api.get<{ jobs: Job[] }>('/jobs?limit=50'),
    refetchInterval: 5000,
  });

  const cancelMut = useMutation({
    mutationFn: (jobId: string) => api.post(`/jobs/${jobId}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const retryMut = useMutation({
    mutationFn: (jobId: string) => api.post(`/jobs/${jobId}/retry`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  });

  const allJobs = data?.jobs ?? [];
  const jobs = statusFilter === 'all'
    ? allJobs
    : allJobs.filter((j) => j.status === statusFilter);

  // Aggregates
  const runningCount = allJobs.filter((j) => j.status === 'running' || j.status === 'processing').length;
  const completedCount = allJobs.filter((j) => j.status === 'completed').length;
  const failedCount = allJobs.filter((j) => j.status === 'failed').length;
  const queuedCount = allJobs.filter((j) => j.status === 'queued').length;

  return (
    <div>
      <PageHeader
        title="Processing Jobs"
        subtitle="Pipeline processing queue"
        actions={
          <span className="text-steel font-telemetry text-xs">
            Auto-refreshes every 5s
          </span>
        }
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Running" value={runningCount} trend={runningCount > 0 ? 'up' : undefined} />
        <StatCard label="Queued" value={queuedCount} />
        <StatCard label="Completed" value={completedCount} />
        <StatCard label="Failed" value={failedCount} />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex gap-3 mb-6">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="all">All Status ({allJobs.length})</option>
          <option value="running">Running ({runningCount})</option>
          <option value="queued">Queued ({queuedCount})</option>
          <option value="completed">Completed ({completedCount})</option>
          <option value="failed">Failed ({failedCount})</option>
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonTableRows rows={6} cols={5} />
      ) : error ? (
        <QueryError message="Couldn't load processing jobs." onRetry={() => refetch()} />
      ) : jobs.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-4xl mb-3" aria-hidden="true">⚙️</div>
          <h2 className="font-monument text-lg text-chalk mb-2">
            {statusFilter !== 'all' ? 'No matching jobs' : 'No processing jobs yet'}
          </h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            {statusFilter !== 'all'
              ? 'No jobs with the selected status. Try changing the filter.'
              : 'Upload a session to start processing. Jobs will appear here as they run through the analysis pipeline.'}
          </p>
          {statusFilter !== 'all' && (
            <button
              onClick={() => setStatusFilter('all')}
              className="mt-3 text-pit-orange font-telemetry text-xs hover:underline"
            >
              Show all jobs
            </button>
          )}
        </div>
      ) : (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/10 text-left">
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Session</th>
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Status</th>
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Stage</th>
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Started</th>
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Duration</th>
                <th scope="col" className="px-4 py-3 text-steel/60 font-telemetry text-[10px] uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-steel/5">
              {jobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-asphalt/50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-chalk font-body text-sm">
                      {job.file_name ?? job.job_id.slice(0, 8)}
                    </div>
                    <div className="text-steel/40 font-telemetry text-[10px]">
                      {job.job_id.slice(0, 12)}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={job.status} />
                    <ProgressBar job={job} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-chalk/60 font-telemetry text-xs">
                      {job.stage_name ?? '—'}
                    </span>
                    {job.stage_index != null && job.stage_total != null && (
                      <span className="text-steel/40 font-telemetry text-[10px] ml-1">
                        ({job.stage_index}/{job.stage_total})
                      </span>
                    )}
                    {job.error_message && (
                      <p className="mt-0.5 text-safety-red font-telemetry text-[10px] truncate max-w-[200px]">
                        {job.error_message}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-steel font-telemetry text-xs">
                    {timeAgo(job.started_at)}
                  </td>
                  <td className="px-4 py-3 text-steel font-telemetry text-xs">
                    {duration(job.started_at, job.completed_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {(job.status === 'running' || job.status === 'processing' || job.status === 'queued') && (
                        <button
                          onClick={() => cancelMut.mutate(job.job_id)}
                          disabled={cancelMut.isPending}
                          className="px-2 py-1 text-[10px] font-telemetry uppercase text-safety-red border border-safety-red/20 rounded
                            hover:bg-safety-red/10 disabled:opacity-50 transition-colors"
                        >
                          Cancel
                        </button>
                      )}
                      {(job.status === 'failed' || job.status === 'cancelled') && (
                        <button
                          onClick={() => retryMut.mutate(job.job_id)}
                          disabled={retryMut.isPending}
                          className="px-2 py-1 text-[10px] font-telemetry uppercase text-acid-green border border-acid-green/20 rounded
                            hover:bg-acid-green/10 disabled:opacity-50 transition-colors"
                        >
                          Retry
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
