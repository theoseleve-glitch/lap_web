'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, FormField } from '@/components/app';

interface NewKartPayload {
  name: string;
  number: string;
  chassis: string;
  engine: string;
  weight_kg: string;
  notes: string;
}

interface KartCreated {
  id: number;
}

export default function NewKartPage() {
  const router = useRouter();
  const [form, setForm] = useState<NewKartPayload>({
    name: '',
    number: '',
    chassis: '',
    engine: '',
    weight_kg: '',
    notes: '',
  });
  const [errors, setErrors] = useState<Partial<NewKartPayload>>({});

  const mutation = useMutation({
    mutationFn: (payload: NewKartPayload) =>
      api.post<KartCreated>('/karts', {
        ...payload,
        weight_kg: payload.weight_kg ? parseFloat(payload.weight_kg) : null,
        number: payload.number || null,
        chassis: payload.chassis || null,
        engine: payload.engine || null,
        notes: payload.notes || null,
      }),
    onSuccess: (data) => {
      router.push(`/app/karts/${data.id}`);
    },
  });

  const handleChange = (field: keyof NewKartPayload) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const validate = (): boolean => {
    const newErrors: Partial<NewKartPayload> = {};
    if (!form.name.trim()) newErrors.name = 'Name is required';
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate(form);
  };

  return (
    <div className="max-w-xl">
      <PageHeader
        title="New Kart"
        subtitle="Add a kart to your fleet"
        actions={
          <button
            onClick={() => router.back()}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            ← Back
          </button>
        }
      />

      <form onSubmit={handleSubmit} className="bg-concrete rounded-lg border border-steel/20 p-6 space-y-1">
        <FormField
          label="Name"
          placeholder="e.g. My Kart / Team Kart #1"
          value={form.name}
          onChange={handleChange('name')}
          error={errors.name}
          required
        />
        <FormField
          label="Number"
          placeholder="e.g. 42"
          value={form.number}
          onChange={handleChange('number')}
        />
        <FormField
          label="Chassis"
          placeholder="e.g. Tony Kart Racer 401R"
          value={form.chassis}
          onChange={handleChange('chassis')}
        />
        <FormField
          label="Engine"
          placeholder="e.g. IAME X30 125cc"
          value={form.engine}
          onChange={handleChange('engine')}
        />
        <FormField
          label="Weight (kg)"
          type="number"
          placeholder="e.g. 165"
          value={form.weight_kg}
          onChange={handleChange('weight_kg')}
          min="0"
          step="0.1"
        />

        <div className="mb-4">
          <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
            Notes
          </label>
          <textarea
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors resize-none"
            placeholder="Optional notes about this kart..."
            rows={3}
            value={form.notes}
            onChange={handleChange('notes')}
          />
        </div>

        {mutation.error && (
          <p className="text-safety-red font-telemetry text-sm py-2">
            {(mutation.error as Error).message}
          </p>
        )}

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-6 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? 'Saving...' : 'Save Kart'}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="px-6 py-2.5 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
