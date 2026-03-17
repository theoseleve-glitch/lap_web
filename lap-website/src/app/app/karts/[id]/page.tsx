'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { StatCard, FormField, QueryError, SkeletonStatCards, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { useEntityDelete } from '@/hooks/useEntityDelete';
import { DeleteConfirmPanel } from '@/components/app/DeleteConfirmPanel';

interface KartDetail {
  id: number;
  name: string;
  manufacturer: string | null;
  model: string | null;
  engine: string | null;
  power_hp: number | null;
  weight_kg: number | null;
  notes: string | null;
  session_count: number;
}

export default function KartDetailPage() {
  const params = useParams();
  const queryClient = useQueryClient();
  const id = params.id as string;

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: '',
    manufacturer: '',
    model: '',
    engine: '',
    power_hp: '',
    weight_kg: '',
    notes: '',
  });

  const { data: kart, isLoading, error, refetch } = useQuery({
    queryKey: ['kart', id],
    queryFn: () => api.get<KartDetail>(`/karts/${id}`),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.patch<KartDetail>(`/karts/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kart', id] });
      queryClient.invalidateQueries({ queryKey: ['karts'] });
      setEditing(false);
    },
  });

  const del = useEntityDelete({
    entity: 'kart',
    id: id,
    endpoint: `/karts/${id}`,
    invalidate: [['karts'], ['sessions']],
    redirectTo: '/app/karts',
  });

  const startEditing = () => {
    if (!kart) return;
    setForm({
      name: kart.name || '',
      manufacturer: kart.manufacturer || '',
      model: kart.model || '',
      engine: kart.engine || '',
      power_hp: kart.power_hp != null ? String(kart.power_hp) : '',
      weight_kg: kart.weight_kg != null ? String(kart.weight_kg) : '',
      notes: kart.notes || '',
    });
    setEditing(true);
  };

  const handleSave = () => {
    if (!form.name.trim()) return;
    updateMutation.mutate({
      name: form.name.trim(),
      manufacturer: form.manufacturer.trim() || null,
      model: form.model.trim() || null,
      engine: form.engine.trim() || null,
      power_hp: form.power_hp ? parseFloat(form.power_hp) : null,
      weight_kg: form.weight_kg ? parseFloat(form.weight_kg) : null,
      notes: form.notes.trim() || null,
    });
  };

  const handleChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
    };

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-40 mb-2" />
          <SkeletonBox className="h-3 w-24" />
        </div>
        <SkeletonStatCards count={3} />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load kart details." onRetry={() => refetch()} />;
  }

  if (!kart) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Kart not found</h2>
        <p className="text-steel font-body text-sm mb-4">This kart may have been deleted or the link is invalid.</p>
        <Link href="/app/karts" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to karts
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageIntro
        title={kart.name}
        subtitle={[kart.manufacturer, kart.model, kart.engine].filter(Boolean).join(' \u00b7 ') || 'Kart details'}
        actions={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={startEditing}
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={del.requestDelete}
              className="px-4 py-2 border border-safety-red/30 text-safety-red font-telemetry text-sm rounded hover:bg-safety-red/10 transition-colors"
            >
              Delete
            </button>
            <Link
              href="/app/karts"
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              \u2190 All Karts
            </Link>
          </div>
        }
      />

      {/* Delete confirmation */}
      <DeleteConfirmPanel {...del} entityName={kart.name} entityType="kart" />

      {/* Edit form */}
      {editing && (
        <div className="bg-concrete rounded-lg border border-pit-orange/30 p-6 mb-6">
          <h2 className="font-monument text-lg text-chalk mb-4">Edit Kart</h2>
          <div className="space-y-1">
            <FormField label="Name" value={form.name} onChange={handleChange('name')} required />
            <FormField label="Manufacturer" value={form.manufacturer} onChange={handleChange('manufacturer')} placeholder="e.g. Tony Kart" />
            <FormField label="Model" value={form.model} onChange={handleChange('model')} placeholder="e.g. Racer 401R" />
            <FormField label="Engine" value={form.engine} onChange={handleChange('engine')} placeholder="e.g. IAME X30" />
            <div className="grid grid-cols-2 gap-4">
              <FormField label="Power (hp)" type="number" value={form.power_hp} onChange={handleChange('power_hp')} min="0" step="0.1" />
              <FormField label="Weight (kg)" type="number" value={form.weight_kg} onChange={handleChange('weight_kg')} min="0" step="0.1" />
            </div>
            <div className="mb-4">
              <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">Notes</label>
              <textarea
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 resize-none"
                rows={3}
                value={form.notes}
                onChange={handleChange('notes')}
              />
            </div>
          </div>
          {updateMutation.error && (
            <p className="text-safety-red font-telemetry text-sm mb-2">
              {(updateMutation.error as Error).message}
            </p>
          )}
          <div className="flex gap-2 mt-3">
            <button
              type="button"
              onClick={handleSave}
              disabled={updateMutation.isPending || !form.name.trim()}
              className="px-6 py-2.5 bg-pit-orange text-white font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="px-6 py-2.5 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Sessions" value={kart.session_count} />
        <StatCard label="Power" value={kart.power_hp != null ? `${kart.power_hp}` : '\u2014'} unit="hp" />
        <StatCard label="Weight" value={kart.weight_kg != null ? `${kart.weight_kg}` : '\u2014'} unit="kg" />
      </div>

      {/* Details card */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4">
        <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">Details</h2>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {kart.manufacturer && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">Manufacturer</dt>
              <dd className="text-chalk font-body mt-0.5">{kart.manufacturer}</dd>
            </div>
          )}
          {kart.model && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">Model</dt>
              <dd className="text-chalk font-body mt-0.5">{kart.model}</dd>
            </div>
          )}
          {kart.engine && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">Engine</dt>
              <dd className="text-chalk font-body mt-0.5">{kart.engine}</dd>
            </div>
          )}
          {kart.weight_kg != null && (
            <div>
              <dt className="text-steel font-telemetry text-xs uppercase">Weight</dt>
              <dd className="text-chalk font-body mt-0.5">{kart.weight_kg} kg</dd>
            </div>
          )}
        </dl>
        {kart.notes && (
          <div className="mt-3 pt-3 border-t border-steel/10">
            <dt className="text-steel font-telemetry text-xs uppercase mb-1">Notes</dt>
            <dd className="text-chalk font-body text-sm">{kart.notes}</dd>
          </div>
        )}
      </div>
    </div>
  );
}
