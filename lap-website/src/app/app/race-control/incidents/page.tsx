'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { AdminTable } from '@/components/admin/AdminTable';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function IncidentsPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: '', body: '', severity: 'p3' });

  const { data, isLoading } = useQuery({
    queryKey: ['admin-incidents'],
    queryFn: () => adminApi.listIncidents(),
  });

  const createMutation = useMutation({
    mutationFn: () => adminApi.createIncident(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-incidents'] });
      setShowForm(false);
      setForm({ title: '', body: '', severity: 'p3' });
    },
  });

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-chalk">Incidents</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded bg-red-500/20 px-3 py-1 text-xs font-medium text-red-400 hover:bg-red-500/30"
        >
          {showForm ? 'Cancel' : 'New Incident'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4 rounded-lg border border-red-500/20 bg-concrete p-4 max-w-lg">
          <input
            placeholder="Title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30"
          />
          <textarea
            placeholder="Description..."
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk placeholder-white/30"
            rows={3}
          />
          <select
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value })}
            className="mb-2 rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk"
          >
            <option value="p1">P1 - Critical</option>
            <option value="p2">P2 - High</option>
            <option value="p3">P3 - Medium</option>
            <option value="p4">P4 - Low</option>
          </select>
          <div>
            <button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !form.title}
              className="rounded bg-red-500/20 px-3 py-1 text-xs text-red-400 disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating...' : 'Create Incident'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : (
        <AdminTable
          columns={[
            { key: 'severity', label: 'Severity', render: (r) => <StatusBadge status={r.severity as string} /> },
            { key: 'title', label: 'Title' },
            { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status as string} /> },
            { key: 'created_at', label: 'Created', render: (r) => new Date(r.created_at as string).toLocaleString() },
            { key: 'resolved_at', label: 'Resolved', render: (r) => r.resolved_at ? new Date(r.resolved_at as string).toLocaleString() : '-' },
          ]}
          data={data ?? []}
        />
      )}
    </div>
  );
}
