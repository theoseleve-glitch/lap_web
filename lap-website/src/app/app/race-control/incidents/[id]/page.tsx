'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ status: '', body: '', severity: '' });

  const { data: incident, isLoading } = useQuery({
    queryKey: ['admin-incident', id],
    queryFn: async () => {
      const list = await adminApi.listIncidents();
      return list?.find((i) => String(i.id) === id) ?? null;
    },
    enabled: !!id,
  });

  const updateMutation = useMutation({
    mutationFn: () => adminApi.updateIncident(Number(id), form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-incident', id] });
      queryClient.invalidateQueries({ queryKey: ['admin-incidents'] });
      setEditing(false);
    },
  });

  if (isLoading) return <p className="text-steel">Loading...</p>;
  if (!incident) return <p className="text-red-400">Incident not found.</p>;

  return (
    <div>
      <button onClick={() => router.back()} className="mb-4 text-xs text-steel hover:text-chalk">
        &larr; Back to Incidents
      </button>

      <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
        <div className="mb-3 flex items-center gap-3">
          <StatusBadge status={incident.severity as string} />
          <StatusBadge status={incident.status as string} />
          <h1 className="text-lg font-bold text-chalk">{incident.title as string}</h1>
        </div>

        <p className="mb-2 text-sm text-chalk/80">{incident.body as string}</p>

        <div className="flex gap-4 text-xs text-steel">
          <span>Created: {new Date(incident.created_at as string).toLocaleString()}</span>
          {incident.resolved_at && (
            <span>Resolved: {new Date(incident.resolved_at as string).toLocaleString()}</span>
          )}
        </div>
      </div>

      {/* Edit form */}
      {!editing ? (
        <button
          onClick={() => {
            setForm({
              status: incident.status as string,
              body: incident.body as string,
              severity: incident.severity as string,
            });
            setEditing(true);
          }}
          className="rounded bg-red-500/20 px-3 py-1 text-xs font-medium text-red-400 hover:bg-red-500/30"
        >
          Edit Incident
        </button>
      ) : (
        <div className="max-w-lg rounded-lg border border-red-500/20 bg-concrete p-4">
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
            className="mb-2 rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk"
          >
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="mitigated">Mitigated</option>
            <option value="resolved">Resolved</option>
          </select>
          <select
            value={form.severity}
            onChange={(e) => setForm({ ...form, severity: e.target.value })}
            className="mb-2 ml-2 rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk"
          >
            <option value="p1">P1 - Critical</option>
            <option value="p2">P2 - High</option>
            <option value="p3">P3 - Medium</option>
            <option value="p4">P4 - Low</option>
          </select>
          <textarea
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            className="mb-2 w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk"
            rows={4}
          />
          <div className="flex gap-2">
            <button
              onClick={() => updateMutation.mutate()}
              disabled={updateMutation.isPending}
              className="rounded bg-red-500/20 px-3 py-1 text-xs text-red-400 disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded px-3 py-1 text-xs text-steel hover:text-chalk"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
