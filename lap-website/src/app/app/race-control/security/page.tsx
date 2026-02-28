'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function SecurityEventsPage() {
  const [typeFilter, setTypeFilter] = useState('');

  const { data: events, isLoading } = useQuery({
    queryKey: ['admin-security-events', typeFilter],
    queryFn: () => adminApi.listSecurityEvents({ type: typeFilter || undefined }),
  });

  const { data: failures } = useQuery({
    queryKey: ['admin-auth-failures'],
    queryFn: adminApi.authFailures,
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Security Events</h1>

      {/* Auth failure highlights */}
      {failures && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-steel">Top Auth Failure IPs (24h)</h2>
          <div className="flex gap-3 flex-wrap">
            {failures.top_ips.slice(0, 5).map((ip) => (
              <div key={ip.ip_address} className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-1.5">
                <span className="font-mono text-xs text-red-400">{ip.ip_address}</span>
                <span className="ml-2 text-xs text-steel">{ip.cnt} failures</span>
              </div>
            ))}
            {failures.top_ips.length === 0 && (
              <span className="text-sm text-green-400">No auth failures in 24h</span>
            )}
          </div>
        </div>
      )}

      {/* Filter */}
      <select
        value={typeFilter}
        onChange={(e) => setTypeFilter(e.target.value)}
        className="mb-4 rounded border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-chalk"
      >
        <option value="">All types</option>
        <option value="login_failed">Login Failed</option>
        <option value="login_success">Login Success</option>
        <option value="auth_denied">Auth Denied</option>
        <option value="token_expired">Token Expired</option>
        <option value="rate_limited">Rate Limited</option>
      </select>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'event_type', label: 'Type', render: (r) => <StatusBadge status={r.event_type as string} /> },
            { key: 'severity', label: 'Severity', render: (r) => <StatusBadge status={r.severity as string} /> },
            { key: 'user_id', label: 'User ID', render: (r) => r.user_id ?? '-' },
            { key: 'ip_address', label: 'IP', render: (r) => <span className="font-mono text-xs">{String(r.ip_address ?? '-')}</span> },
            { key: 'created_at', label: 'Time', render: (r) => new Date(r.created_at as string).toLocaleString() },
          ]}
          data={events ?? []}
        />
      )}
    </div>
  );
}
