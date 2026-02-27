"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";

type Job = {
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
};

const STATUS_BADGES: Record<string, { label: string; color: string }> = {
  queued: { label: "Queued", color: "bg-white/10 text-white/50" },
  running: { label: "Running", color: "bg-blue-500/20 text-blue-400" },
  processing: { label: "Processing", color: "bg-blue-500/20 text-blue-400" },
  paused: { label: "Paused", color: "bg-yellow-500/20 text-yellow-400" },
  completed: { label: "Completed", color: "bg-green-500/20 text-green-400" },
  failed: { label: "Failed", color: "bg-red-500/20 text-red-400" },
  cancelled: { label: "Cancelled", color: "bg-white/10 text-white/30" },
};

function StatusBadge({ status }: { status: string }) {
  const badge = STATUS_BADGES[status] ?? {
    label: status,
    color: "bg-white/10 text-white/50",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.color}`}
    >
      {(status === "running" || status === "processing") && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
      )}
      {badge.label}
    </span>
  );
}

function ProgressBar({ job }: { job: Job }) {
  if (
    job.status !== "running" &&
    job.status !== "processing" &&
    job.status !== "queued"
  )
    return null;
  const index = job.stage_index ?? 0;
  const total = job.stage_total ?? 15;
  const pct = total > 0 ? Math.round((index / total) * 100) : 0;

  return (
    <div className="mt-1 flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-[#B6FF2E] transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-white/40">{pct}%</span>
    </div>
  );
}

function timeAgo(isoDate: string | null): string {
  if (!isoDate) return "—";
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function JobsPage() {
  const queryClient = useQueryClient();
  const [limit] = useState(50);

  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs", limit],
    queryFn: async () => {
      return await apiFetch<{ jobs: Job[] }>(`/jobs?limit=${limit}`);
    },
    refetchInterval: 5000,
  });

  const cancelMut = useMutation({
    mutationFn: async (jobId: string) => {
      await apiFetch(`/jobs/${jobId}/cancel`, { method: "POST" });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const retryMut = useMutation({
    mutationFn: async (jobId: string) => {
      await apiFetch(`/jobs/${jobId}/retry`, { method: "POST" });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const jobs = data?.jobs ?? [];

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Processing Jobs</h1>
        <span className="text-sm text-white/40">
          Auto-refreshes every 5s
        </span>
      </div>

      {isLoading && (
        <div className="rounded-lg border border-white/10 bg-white/5 p-12 text-center text-white/40">
          Loading jobs...
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-red-400">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && jobs.length === 0 && (
        <div className="rounded-lg border border-white/10 bg-white/5 p-12 text-center text-white/40">
          No processing jobs yet. Upload a session to get started.
        </div>
      )}

      {jobs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-white/10">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10 bg-white/5 text-left text-xs text-white/40">
                <th className="px-4 py-3 font-medium">Session</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Stage</th>
                <th className="px-4 py-3 font-medium">Started</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {jobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <div className="text-sm text-white">
                      {job.file_name ?? job.job_id.slice(0, 8)}
                    </div>
                    <div className="text-xs text-white/30">
                      {job.job_id.slice(0, 8)}...
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={job.status} />
                    <ProgressBar job={job} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-white/60">
                      {job.stage_name ?? "—"}
                    </span>
                    {job.error_message && (
                      <div className="mt-0.5 text-xs text-red-400">
                        {job.error_message.slice(0, 100)}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-white/40">
                    {timeAgo(job.started_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {(job.status === "running" ||
                        job.status === "processing" ||
                        job.status === "queued") && (
                        <button
                          onClick={() => cancelMut.mutate(job.job_id)}
                          disabled={cancelMut.isPending}
                          className="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      )}
                      {(job.status === "failed" ||
                        job.status === "cancelled") && (
                        <button
                          onClick={() => retryMut.mutate(job.job_id)}
                          disabled={retryMut.isPending}
                          className="rounded px-2 py-1 text-xs text-[#B6FF2E] hover:bg-[#B6FF2E]/10 disabled:opacity-50"
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
