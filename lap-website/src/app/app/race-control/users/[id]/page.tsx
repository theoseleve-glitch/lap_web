'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { ActionButton } from '@/components/admin/ActionButton';

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const userId = Number(id);
  const queryClient = useQueryClient();

  const { data: user, isLoading } = useQuery({
    queryKey: ['admin-user', userId],
    queryFn: () => adminApi.getUser(userId),
  });

  const { data: timeline } = useQuery({
    queryKey: ['admin-user-timeline', userId],
    queryFn: () => adminApi.getUserTimeline(userId),
  });

  if (isLoading) return <p className="text-steel">Loading...</p>;
  if (!user) return <p className="text-red-400">User not found</p>;

  return (
    <div>
      <h1 className="mb-2 text-xl font-bold text-chalk">{user.email}</h1>
      <div className="mb-6 flex gap-2">
        <StatusBadge status={user.plan_tier ?? 'demo'} />
        <StatusBadge status={user.subscription_status ?? 'none'} />
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Plan" value={user.plan_tier ?? 'demo'} />
        <MetricCard label="Joined" value={new Date(user.created_at).toLocaleDateString()} />
        <MetricCard label="Admin" value={user.is_superadmin ? 'Yes' : 'No'} />
        <MetricCard label="Workspaces" value={user.workspaces?.length ?? 0} />
      </div>

      {/* Workspaces */}
      {user.workspaces && user.workspaces.length > 0 && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-steel">Workspaces</h2>
          <div className="rounded-lg border border-white/10">
            {user.workspaces.map((ws) => (
              <div key={ws.id} className="flex items-center justify-between border-b border-white/5 px-4 py-2 last:border-0">
                <span className="text-sm text-chalk/80">{ws.name}</span>
                <StatusBadge status={ws.role} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-steel">Actions</h2>
        <ActionButton
          label="Invalidate Sessions"
          variant="danger"
          onConfirm={async (reason) => {
            await adminApi.invalidateSessions(userId, reason);
            queryClient.invalidateQueries({ queryKey: ['admin-user', userId] });
          }}
        />
      </div>

      {/* Timeline */}
      <div>
        <h2 className="mb-2 text-sm font-semibold text-steel">Recent Activity</h2>
        <div className="space-y-1">
          {(timeline ?? []).slice(0, 20).map((event: Record<string, unknown>, i: number) => (
            <div key={i} className="flex items-center gap-3 rounded border border-white/5 px-3 py-1.5 text-xs">
              <span className="text-steel">{String(event.created_at ?? '').slice(0, 19)}</span>
              <StatusBadge status={String(event.event_type ?? 'unknown')} />
              <span className="text-chalk/60 truncate">{String(event.source ?? '')}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
