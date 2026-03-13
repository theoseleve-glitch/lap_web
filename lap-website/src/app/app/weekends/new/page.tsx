'use client';

import { useState, useId } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { FormField } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

interface TrackOption {
  id: number;
  name: string;
}

interface NewWeekendPayload {
  name: string;
  track_id: number | null;
  start_date: string;
  end_date: string;
  notes: string;
}

interface WeekendCreated {
  id: number;
}

export default function NewWeekendPage() {
  const router = useRouter();
  const fieldId = useId();
  const [form, setForm] = useState({
    name: '',
    track_id: '',
    start_date: '',
    end_date: '',
    notes: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const { data: tracksData } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<TrackOption[]>('/tracks'),
  });
  const tracks = Array.isArray(tracksData) ? tracksData : [];

  const mutation = useMutation({
    mutationFn: (payload: NewWeekendPayload) =>
      api.post<WeekendCreated>('/weekends', payload),
    onSuccess: (data) => {
      router.push(`/app/weekends/${data.id}`);
    },
  });

  const handleChange = (field: string) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
  ) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }));
    if (errors[field]) {
      setErrors((prev) => { const next = { ...prev }; delete next[field]; return next; });
    }
  };

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    if (!form.name.trim()) newErrors.name = 'Name is required';
    if (!form.start_date) newErrors.start_date = 'Start date is required';
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate({
      name: form.name,
      track_id: form.track_id ? parseInt(form.track_id, 10) : null,
      start_date: form.start_date,
      end_date: form.end_date || form.start_date,
      notes: form.notes || '',
    });
  };

  return (
    <div className="max-w-xl">
      <PageIntro
        title="New Weekend"
        subtitle="Group sessions into a race weekend"
        actions={
          <button
            type="button"
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
          placeholder="e.g. Round 3 – Silverstone"
          value={form.name}
          onChange={handleChange('name')}
          error={errors.name}
          required
        />

        <div className="mb-4">
          <label htmlFor={`${fieldId}-track`} className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
            Track
          </label>
          <select
            id={`${fieldId}-track`}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            value={form.track_id}
            onChange={handleChange('track_id')}
          >
            <option value="">Select a track...</option>
            {tracks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        <FormField
          label="Start Date"
          type="date"
          value={form.start_date}
          onChange={handleChange('start_date')}
          error={errors.start_date}
          required
        />
        <FormField
          label="End Date"
          type="date"
          value={form.end_date}
          onChange={handleChange('end_date')}
          min={form.start_date || undefined}
        />

        <div className="mb-4">
          <label htmlFor={`${fieldId}-notes`} className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
            Notes
          </label>
          <textarea
            id={`${fieldId}-notes`}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors resize-none"
            placeholder="Optional notes about this weekend..."
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
            {mutation.isPending ? 'Saving...' : 'Save Weekend'}
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
