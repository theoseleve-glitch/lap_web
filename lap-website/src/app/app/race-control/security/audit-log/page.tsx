'use client';

import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';

export default function AuditLogPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin-audit-log'],
    queryFn: () => adminApi.listAuditLog({ limit: 100 }),
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Audit Log</h1>
      <p className="mb-4 text-xs text-steel">Immutable record of all admin actions.</p>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'created_at', label: 'Time', render: (r) => new Date(r.created_at as string).toLocaleString() },
            { key: 'admin_user_id', label: 'Admin' },
            { key: 'action', label: 'Action' },
            { key: 'target_type', label: 'Target' },
            { key: 'target_id', label: 'Target ID' },
            { key: 'reason', label: 'Reason', render: (r) => <span className="text-xs text-chalk/60 truncate max-w-[200px] inline-block">{String(r.reason ?? '-')}</span> },
          ]}
          data={data ?? []}
        />
      )}
    </div>
  );
}
