'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import StorageBar from '@/components/admin/StorageBar';

type User = {
  id: number;
  email: string;
  display_name: string | null;
  plan_tier: string | null;
  subscription_status: string | null;
  created_at: string | null;
  email_verified: boolean | null;
  suspended_at: string | null;
  is_platform_admin: boolean;
};

type ActivityResponse = {
  events_30d: number;
  last_active: string | null;
  sessions_viewed: number;
  uploads_30d: number;
  top_features: { event_type: string; count: number }[];
  recent: {
    event_type: string;
    path: string;
    properties: Record<string, unknown>;
    created_at: string;
  }[];
};

type StorageResponse = {
  total_reports: number;
  reports_this_month: number;
  total_storage_bytes: number;
  avg_storage_per_session_bytes: number;
  plan_tier: string;
  plan_storage_limit_bytes: number;
  storage_pct: number;
  analyses_used: number;
  analyses_limit: number;
};

function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e3).toFixed(0)} KB`;
}

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <p className="text-xs text-white/40">{label}</p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
      {sub && <p className="mt-1 text-xs text-white/30">{sub}</p>}
    </div>
  );
}

function eventBadgeClass(eventType: string): string {
  if (eventType.startsWith('session.')) {
    return 'bg-[#C9A84C]/15 text-[#C9A84C] border border-[#C9A84C]/30';
  }
  if (eventType.startsWith('chart.') || eventType.startsWith('compare.')) {
    return 'bg-[#8B5CF6]/15 text-[#8B5CF6] border border-[#8B5CF6]/30';
  }
  if (eventType.startsWith('report.')) {
    return 'bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30';
  }
  if (eventType.startsWith('limit.')) {
    return 'bg-[#FF2A2A]/15 text-[#FF2A2A] border border-[#FF2A2A]/30';
  }
  return 'bg-white/[0.08] text-white/50 border border-white/10';
}

export default function UserDetailPage() {
  const params = useParams();
  const id = params?.id as string;

  const { data: user, isLoading: userLoading } = useQuery({
    queryKey: ['admin-user', id],
    queryFn: () => apiFetch<User>(`/admin/users/${id}`),
    enabled: !!id,
  });

  const { data: activity } = useQuery({
    queryKey: ['admin-user-activity', id],
    queryFn: () => apiFetch<ActivityResponse>(`/admin/users/${id}/activity`),
    enabled: !!id,
  });

  const { data: storageData } = useQuery({
    queryKey: ['admin-user-storage', id],
    queryFn: () => apiFetch<StorageResponse>(`/admin/users/${id}/storage`),
    enabled: !!id,
  });

  if (userLoading) {
    return (
      <div className="mx-auto max-w-5xl">
        <p className="text-center text-white/40">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="mx-auto max-w-5xl">
        <p className="text-center text-white/40">User not found.</p>
      </div>
    );
  }

  const initials = (user.display_name ?? user.email).charAt(0).toUpperCase();

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* Back link */}
      <Link
        href="/admin/users"
        className="inline-block text-sm text-white/40 hover:text-white transition-colors"
      >
        ← Back to Users
      </Link>

      {/* User header */}
      <div className="flex items-center gap-4 rounded-lg border border-white/10 bg-white/[0.03] p-5">
        <div
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-lg font-bold text-white"
          style={{ backgroundColor: '#C9A84C' }}
        >
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-bold text-white">
            {user.display_name ?? user.email}
          </p>
          <p className="text-sm text-white/50">{user.email}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {/* Plan badge */}
          <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs text-white/60">
            {user.plan_tier ?? 'demo'}
          </span>
          {/* Status badge */}
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs border ${
              user.suspended_at
                ? 'border-safety-red/20 bg-safety-red/15 text-safety-red'
                : user.subscription_status === 'active'
                  ? 'border-acid-green/20 bg-acid-green/15 text-acid-green'
                  : 'border-white/10 bg-white/5 text-white/50'
            }`}
          >
            {user.suspended_at
              ? 'Suspended'
              : (user.subscription_status ?? 'free')}
          </span>
          {/* Join date */}
          <span className="text-xs text-white/30">
            Joined{' '}
            {user.created_at
              ? new Date(user.created_at).toLocaleDateString()
              : '—'}
          </span>
        </div>
      </div>

      {/* Two-column panels */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Activity panel */}
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
          <h2 className="mb-4 text-sm font-medium text-white">Activity</h2>
          <div className="mb-4 grid grid-cols-2 gap-3">
            <MetricCard
              label="Events (30d)"
              value={activity?.events_30d ?? '—'}
            />
            <MetricCard
              label="Sessions Viewed"
              value={activity?.sessions_viewed ?? '—'}
            />
            <MetricCard
              label="Uploads (30d)"
              value={activity?.uploads_30d ?? '—'}
            />
            <MetricCard
              label="Last Active"
              value={
                activity?.last_active
                  ? new Date(activity.last_active).toLocaleDateString()
                  : '—'
              }
            />
          </div>

          {activity?.top_features && activity.top_features.length > 0 && (
            <div>
              <p className="mb-2 text-xs text-white/40">Top Features</p>
              <div className="space-y-1">
                {activity.top_features.map((f) => (
                  <div key={f.event_type} className="flex items-center justify-between text-xs">
                    <span className="text-white/60">{f.event_type}</span>
                    <span className="tabular-nums text-white/40">{f.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Storage panel */}
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
          <h2 className="mb-4 text-sm font-medium text-white">Storage &amp; Usage</h2>
          <div className="mb-4 grid grid-cols-2 gap-3">
            <MetricCard
              label="Total Reports"
              value={storageData?.total_reports ?? '—'}
            />
            <MetricCard
              label="Reports (Month)"
              value={storageData?.reports_this_month ?? '—'}
            />
            <MetricCard
              label="Storage Used"
              value={storageData ? formatBytes(storageData.total_storage_bytes) : '—'}
            />
            <MetricCard
              label="Avg / Session"
              value={
                storageData
                  ? formatBytes(storageData.avg_storage_per_session_bytes)
                  : '—'
              }
            />
          </div>

          {storageData && (
            <div className="space-y-4">
              <StorageBar
                label="Storage Used"
                used={storageData.total_storage_bytes}
                limit={storageData.plan_storage_limit_bytes}
                formatValue={formatBytes}
              />
              <StorageBar
                label="Analyses This Month"
                used={storageData.analyses_used}
                limit={storageData.analyses_limit}
                formatValue={(n) => String(n)}
              />
            </div>
          )}
        </div>
      </div>

      {/* Recent events table */}
      {activity?.recent && activity.recent.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-white/[0.03] p-5">
          <h2 className="mb-4 text-sm font-medium text-white">Recent Events</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-white/40">
                  <th className="pb-2 pr-3 font-medium">Time</th>
                  <th className="pb-2 pr-3 font-medium">Event</th>
                  <th className="pb-2 font-medium">Path</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {activity.recent.map((event, i) => (
                  <tr key={i}>
                    <td className="py-2 pr-3 tabular-nums text-white/30">
                      {new Date(event.created_at).toLocaleTimeString()}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`rounded px-1.5 py-0.5 font-medium ${eventBadgeClass(event.event_type)}`}
                      >
                        {event.event_type}
                      </span>
                    </td>
                    <td className="max-w-xs truncate py-2 text-white/30" title={event.path}>
                      {event.path}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
