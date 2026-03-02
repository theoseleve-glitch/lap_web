'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, SkeletonStatCards, SkeletonBox } from '@/components/app';

interface JobDetail {
  id: string;
  file_name: string;
  file_size_mb: number | null;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  duration_s: number | null;
  peak_rss_mb: number | null;
  throughput_mb_s: number | null;
  rows_processed: number | null;
  chunks_written: number | null;
  checksum: string | null;
  error_message: string | null;
  session_id: string | null;
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return 'text-acid-green bg-acid-green/10 border-acid-green/30';
    case 'processing': return 'text-pit-orange bg-pit-orange/10 border-pit-orange/30';
    case 'failed': return 'text-safety-red bg-safety-red/10 border-safety-red/30';
    case 'pending': return 'text-steel bg-steel/10 border-steel/30';
    default: return 'text-steel bg-steel/10 border-steel/30';
  }
}

function formatDuration(s: number | null): string {
  if (s == null) return '—';
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
}

export default function DataHealthDetailPage() {
  const params = useParams();

  const id = params.id as string;

  const { data: job, isLoading, error } = useQuery({
    queryKey: ['data-health-job', id],
    queryFn: () => api.get<JobDetail>(`/data-health/jobs/${id}`),
    refetchInterval: (query) =>
      query.state.data?.status === 'processing' || query.state.data?.status === 'pending'
        ? 2000
        : false,
  });

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-48 mb-2" />
          <SkeletonBox className="h-3 w-32" />
        </div>
        <SkeletonStatCards count={4} />
        <SkeletonBox className="h-48 w-full mt-6 rounded-lg" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="text-center py-16">
        <p className="text-steel font-body">Job not found.</p>
        <Link
          href="/app/data-health"
          className="mt-4 inline-block text-acid-green font-telemetry text-sm hover:underline"
        >
          ← Back to Data Health
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Processing Job"
        subtitle={job.file_name}
        actions={
          <div className="flex items-center gap-3">
            {job.session_id && (
              <Link
                href={`/app/sessions/${job.session_id}`}
                className="px-4 py-2 bg-acid-green/10 text-acid-green border border-acid-green/30 font-telemetry text-sm rounded hover:bg-gold/20 transition-colors"
              >
                View Session →
              </Link>
            )}
            <Link
              href="/app/data-health"
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              ← Back
            </Link>
          </div>
        }
      />

      <div className="mb-6">
        <span className={`inline-flex items-center px-3 py-1 rounded border font-telemetry text-sm uppercase tracking-wide ${statusColor(job.status)}`}>
          {job.status === 'processing' && (
            <span className="w-2 h-2 rounded-full bg-pit-orange animate-pulse mr-2" />
          )}
          {job.status}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Duration"
          value={formatDuration(job.duration_s)}
        />
        <StatCard
          label="Peak RAM"
          value={job.peak_rss_mb != null ? `${job.peak_rss_mb.toFixed(0)}` : '—'}
          unit={job.peak_rss_mb != null ? 'MB' : undefined}
        />
        <StatCard
          label="Throughput"
          value={job.throughput_mb_s != null ? `${job.throughput_mb_s.toFixed(1)}` : '—'}
          unit={job.throughput_mb_s != null ? 'MB/s' : undefined}
        />
        <StatCard
          label="Rows Processed"
          value={job.rows_processed != null ? job.rows_processed.toLocaleString() : '—'}
        />
      </div>

      <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
        <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-4">File Details</h2>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <dt className="text-steel font-telemetry text-xs uppercase mb-1">File Name</dt>
            <dd className="text-chalk font-body text-sm break-all">{job.file_name}</dd>
          </div>
          {job.file_size_mb != null && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase mb-1">File Size</dt>
              <dd className="text-chalk font-body text-sm">{job.file_size_mb.toFixed(2)} MB</dd>
            </div>
          )}
          {job.chunks_written != null && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase mb-1">Chunks Written</dt>
              <dd className="text-chalk font-body text-sm">{job.chunks_written}</dd>
            </div>
          )}
          {job.checksum && (
            <div className="md:col-span-2">
              <dt className="text-steel font-telemetry text-xs uppercase mb-1">Checksum (SHA-256)</dt>
              <dd className="text-steel font-telemetry text-xs break-all">{job.checksum}</dd>
            </div>
          )}
        </dl>
      </div>

      {(job.started_at || job.completed_at) && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
          <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-4">Timeline</h2>
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {job.started_at && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase mb-1">Started</dt>
                <dd className="text-chalk font-body text-sm">{job.started_at}</dd>
              </div>
            )}
            {job.completed_at && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase mb-1">Completed</dt>
                <dd className="text-chalk font-body text-sm">{job.completed_at}</dd>
              </div>
            )}
          </dl>
        </div>
      )}

      {job.error_message && (
        <div className="bg-safety-red/5 border border-safety-red/30 rounded-lg p-5">
          <h2 className="font-telemetry text-xs uppercase tracking-wider text-safety-red mb-3">
            Error Details
          </h2>
          <pre className="text-safety-red font-telemetry text-xs whitespace-pre-wrap break-all leading-relaxed">
            {job.error_message}
          </pre>
        </div>
      )}
    </div>
  );
}
