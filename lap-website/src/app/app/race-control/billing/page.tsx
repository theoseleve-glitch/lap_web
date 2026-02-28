'use client';

import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function AdminBillingPage() {
  const { data: revenue } = useQuery({
    queryKey: ['admin-revenue'],
    queryFn: adminApi.revenue,
  });

  const { data: subs, isLoading } = useQuery({
    queryKey: ['admin-subscriptions'],
    queryFn: adminApi.listSubscriptions,
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Billing Overview</h1>

      {revenue && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
          <MetricCard label="Active Subscriptions" value={revenue.total_active} />
          <MetricCard label="Churned (30d)" value={revenue.churned_30d} status={revenue.churned_30d > 5 ? 'warning' : 'ok'} />
          <MetricCard label="Tiers" value={revenue.tier_breakdown.length} />
        </div>
      )}

      {/* Tier breakdown */}
      {revenue?.tier_breakdown && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold text-steel">Tier Breakdown</h2>
          <div className="flex gap-3">
            {revenue.tier_breakdown.map((t) => (
              <div key={t.plan_tier} className="rounded-lg border border-white/10 bg-concrete px-4 py-2">
                <p className="text-xs text-steel">{t.plan_tier}</p>
                <p className="text-lg font-bold text-chalk">{t.cnt}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Subscriptions table */}
      <h2 className="mb-2 text-sm font-semibold text-steel">Subscriptions</h2>
      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'email', label: 'Email' },
            { key: 'plan_tier', label: 'Plan' },
            { key: 'subscription_status', label: 'Status', render: (r) => <StatusBadge status={r.subscription_status as string} /> },
            { key: 'created_at', label: 'Since', render: (r) => new Date(r.created_at as string).toLocaleDateString() },
          ]}
          data={subs ?? []}
        />
      )}
    </div>
  );
}
