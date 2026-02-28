'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function WebhooksPage() {
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['admin-webhooks', statusFilter],
    queryFn: () => adminApi.listWebhooks({ status: statusFilter || undefined }),
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Webhook Log</h1>

      <select
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
        className="mb-4 rounded border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-chalk"
      >
        <option value="">All statuses</option>
        <option value="processed">Processed</option>
        <option value="pending">Pending</option>
        <option value="failed">Failed</option>
      </select>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'stripe_event_id', label: 'Event ID', render: (r) => String(r.stripe_event_id).slice(0, 20) },
            { key: 'event_type', label: 'Type' },
            { key: 'processing_status', label: 'Status', render: (r) => <StatusBadge status={r.processing_status as string} /> },
            { key: 'error_message', label: 'Error', render: (r) => r.error_message ? <span className="text-red-400 text-xs">{String(r.error_message).slice(0, 50)}</span> : '-' },
            { key: 'created_at', label: 'Time', render: (r) => new Date(r.created_at as string).toLocaleString() },
          ]}
          data={data ?? []}
        />
      )}
    </div>
  );
}
