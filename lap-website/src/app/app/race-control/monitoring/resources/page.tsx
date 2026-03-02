'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { AdminTable } from '@/components/admin/AdminTable';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export default function UserResourcesPage() {
  const [selectedUser, setSelectedUser] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState('total_storage_bytes');

  const { data: totals } = useQuery({
    queryKey: ['admin-monitoring-totals'],
    queryFn: adminApi.monitoringTotals,
    refetchInterval: 60000,
  });

  const { data: users } = useQuery({
    queryKey: ['admin-monitoring-users', sortBy],
    queryFn: () => adminApi.userResources({ sort: sortBy }),
  });

  const { data: timeseries } = useQuery({
    queryKey: ['admin-monitoring-timeseries', selectedUser],
    queryFn: () => adminApi.userTimeseries(selectedUser!, 30),
    enabled: selectedUser !== null,
  });

  return (
    <div>
      <h1 className="mb-6 text-xl font-bold text-chalk">User Resources</h1>

      {/* System totals */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Total Users" value={totals?.total_users ?? 0} status="ok" />
        <MetricCard label="Total Sessions" value={totals?.total_sessions ?? 0} status="ok" />
        <MetricCard
          label="Total Storage"
          value={formatBytes(totals?.total_storage_bytes ?? 0)}
          status="ok"
        />
        <MetricCard
          label="Total Compute"
          value={formatDuration(totals?.total_compute_seconds ?? 0)}
          status="ok"
        />
      </div>

      {/* Sort controls */}
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs text-steel">Sort by:</span>
        {[
          { key: 'total_storage_bytes', label: 'Storage' },
          { key: 'total_compute_seconds', label: 'Compute' },
          { key: 'session_count', label: 'Sessions' },
          { key: 'last_upload', label: 'Last Upload' },
        ].map(opt => (
          <button
            key={opt.key}
            onClick={() => setSortBy(opt.key)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              sortBy === opt.key
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* User table */}
      <AdminTable
        columns={[
          { key: 'email', label: 'Email' },
          { key: 'display_name', label: 'Name', render: (r) => r.display_name ?? '-' },
          { key: 'session_count', label: 'Sessions' },
          { key: 'total_storage_bytes', label: 'Storage', render: (r) => formatBytes(r.total_storage_bytes) },
          { key: 'total_compute_seconds', label: 'Compute', render: (r) => formatDuration(r.total_compute_seconds) },
          { key: 'last_upload', label: 'Last Upload', render: (r) => r.last_upload ? new Date(r.last_upload).toLocaleDateString() : '-' },
        ]}
        data={users ?? []}
        onRowClick={(row) => setSelectedUser(row.user_id)}
        emptyMessage="No users found"
      />

      {/* Time series panel */}
      {selectedUser && timeseries && (
        <div className="mt-6 rounded-lg border border-white/10 bg-concrete p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-steel">
              Daily Usage — {users?.find(u => u.user_id === selectedUser)?.email ?? `User #${selectedUser}`}
            </h2>
            <button
              onClick={() => setSelectedUser(null)}
              className="text-xs text-steel hover:text-chalk"
            >
              Close
            </button>
          </div>

          {timeseries.length === 0 ? (
            <p className="text-sm text-steel/60">No usage data for this period</p>
          ) : (
            <div className="overflow-x-auto">
              {/* Simple bar chart using CSS */}
              <div className="flex items-end gap-1" style={{ height: '120px' }}>
                {timeseries.map((d, i) => {
                  const maxBytes = Math.max(...timeseries.map(t => t.storage_bytes), 1);
                  const pct = (d.storage_bytes / maxBytes) * 100;
                  return (
                    <div key={i} className="group relative flex-1 min-w-[8px]">
                      <div
                        className="w-full rounded-t bg-acid-green/40 transition-colors group-hover:bg-gold/60"
                        style={{ height: `${Math.max(pct, 2)}%` }}
                      />
                      <div className="absolute -top-16 left-1/2 -translate-x-1/2 hidden group-hover:block rounded bg-concrete border border-white/10 px-2 py-1 text-[10px] text-chalk whitespace-nowrap z-10">
                        {d.day}<br />{formatBytes(d.storage_bytes)}<br />{d.uploads} uploads
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-steel/60">
                <span>{timeseries[0]?.day}</span>
                <span>{timeseries[timeseries.length - 1]?.day}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
