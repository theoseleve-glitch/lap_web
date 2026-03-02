'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function EntitlementsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ user_id: '', override_key: '', override_value: '', reason: '' });

  const { data: plans } = useQuery({
    queryKey: ['admin-plans'],
    queryFn: adminApi.listPlans,
  });

  const { data: anomalies } = useQuery({
    queryKey: ['admin-anomalies'],
    queryFn: adminApi.listAnomalies,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      adminApi.createOverride({
        user_id: Number(form.user_id),
        override_key: form.override_key,
        override_value: form.override_value,
        reason: form.reason,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-anomalies'] });
      setShowForm(false);
      setForm({ user_id: '', override_key: '', override_value: '', reason: '' });
    },
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Entitlements</h1>

      {/* Plan definitions */}
      <h2 className="mb-2 text-sm font-semibold text-steel">Plan Definitions</h2>
      {plans && (
        <AdminTable
          columns={[
            { key: 'tier', label: 'Tier' },
            { key: 'reports_per_month', label: 'Reports/mo' },
            { key: 'max_upload_size_mb', label: 'Max Upload MB' },
            { key: 'rate_multiplier', label: 'Rate Multiplier' },
          ]}
          data={plans}
        />
      )}

      {/* Anomalies */}
      <div className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-steel">Anomalies</h2>
        {anomalies && anomalies.length > 0 ? (
          <AdminTable
            columns={[
              { key: 'anomaly_type', label: 'Type', render: (r) => <StatusBadge status={r.anomaly_type as string} /> },
              { key: 'severity', label: 'Severity', render: (r) => <StatusBadge status={r.severity as string} /> },
              { key: 'user_id', label: 'User ID' },
              { key: 'details', label: 'Details', render: (r) => <span className="text-xs text-steel">{JSON.stringify(r.details).slice(0, 80)}</span> },
            ]}
            data={anomalies}
          />
        ) : (
          <p className="text-sm text-green-400">No anomalies detected.</p>
        )}
      </div>

      {/* Create override */}
      <div className="mt-6">
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded bg-acid-green/20 px-3 py-1 text-xs font-medium text-acid-green hover:bg-gold/30 transition-colors"
        >
          {showForm ? 'Cancel' : 'Create Override'}
        </button>

        {showForm && (
          <div className="mt-3 rounded-lg border border-white/10 bg-concrete p-4 max-w-md">
            <label htmlFor="ent-user-id" className="sr-only">User ID</label>
            <input id="ent-user-id" type="number" placeholder="User ID" value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} disabled={createMutation.isPending} className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30 disabled:opacity-60 disabled:cursor-not-allowed" />
            <label htmlFor="ent-key" className="sr-only">Override key</label>
            <input id="ent-key" placeholder="Key (e.g. reports_per_month)" value={form.override_key} onChange={(e) => setForm({ ...form, override_key: e.target.value })} disabled={createMutation.isPending} className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30 disabled:opacity-60 disabled:cursor-not-allowed" />
            <label htmlFor="ent-value" className="sr-only">Override value</label>
            <input id="ent-value" placeholder="Value" value={form.override_value} onChange={(e) => setForm({ ...form, override_value: e.target.value })} disabled={createMutation.isPending} className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30 disabled:opacity-60 disabled:cursor-not-allowed" />
            <label htmlFor="ent-reason" className="sr-only">Reason</label>
            <input id="ent-reason" placeholder="Reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} disabled={createMutation.isPending} className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30 disabled:opacity-60 disabled:cursor-not-allowed" />
            <button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !form.override_key || !form.reason}
              className="rounded bg-acid-green/20 px-3 py-1 text-xs text-acid-green disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
