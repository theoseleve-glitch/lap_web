'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { ActionButton } from '@/components/admin/ActionButton';

export default function ReconciliationPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['admin-reconciliation'],
    queryFn: adminApi.reconciliation,
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Reconciliation</h1>
      <p className="mb-4 text-sm text-steel">
        Users with active subscriptions but demo/missing plan tier.
      </p>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (data ?? []).length === 0 ? (
        <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-4 text-sm text-green-400">
          No mismatches found. All tiers are consistent.
        </div>
      ) : (
        <AdminTable
          columns={[
            { key: 'email', label: 'Email' },
            { key: 'plan_tier', label: 'DB Tier', render: (r) => <StatusBadge status={r.plan_tier as string ?? 'none'} /> },
            { key: 'subscription_status', label: 'Sub Status', render: (r) => <StatusBadge status={r.subscription_status as string} /> },
            {
              key: 'actions',
              label: 'Actions',
              render: (r) => (
                <ActionButton
                  label="Heal"
                  variant="danger"
                  onConfirm={async (reason) => {
                    await adminApi.healMismatch(r.id as number, reason);
                    queryClient.invalidateQueries({ queryKey: ['admin-reconciliation'] });
                  }}
                />
              ),
            },
          ]}
          data={data ?? []}
        />
      )}
    </div>
  );
}
