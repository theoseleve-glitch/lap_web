'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function AdminUsersPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-users', search],
    queryFn: () => adminApi.listUsers({ q: search || undefined }),
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Users</h1>

      <label htmlFor="user-search" className="sr-only">Search users by email</label>
      <input
        id="user-search"
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by email..."
        className="mb-4 w-full max-w-md rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-chalk placeholder-white/30"
      />

      {error && (
        <div className="mb-4 rounded-lg border border-safety-red/30 bg-safety-red/10 p-3 text-safety-red text-sm font-body">
          Failed to load users: {(error as Error).message}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center h-32">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <AdminTable
          columns={[
            { key: 'email', label: 'Email' },
            { key: 'plan_tier', label: 'Plan', render: (r) => <StatusBadge status={r.plan_tier as string} /> },
            { key: 'subscription_status', label: 'Status', render: (r) => <StatusBadge status={r.subscription_status as string ?? 'none'} /> },
            { key: 'created_at', label: 'Joined', render: (r) => new Date(r.created_at as string).toLocaleDateString() },
          ]}
          data={data ?? []}
          onRowClick={(row) => router.push(`/app/race-control/users/${row.id}`)}
          emptyMessage={search ? `No users match "${search}"` : 'No users registered yet'}
        />
      )}
    </div>
  );
}
