'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter, useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader } from '@/components/app';
import { useEntitlementsStore } from '@/lib/entitlements-store';
import { RaceConfigForm, type RaceFormData } from '@/components/app/race-strategy/RaceConfigForm';

interface RaceDetail {
  race: Record<string, unknown>;
  drivers: Array<Record<string, unknown>>;
  windows: Array<Record<string, unknown>>;
  stints: unknown[];
  pit_stops: unknown[];
}

export default function EditRacePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState('');
  const raceStrategyLimit = useEntitlementsStore((s) => s.entitlements?.raceStrategyLimit) as string | undefined;

  const { data, isLoading } = useQuery({
    queryKey: ['race-strategy', id],
    queryFn: () => api.get<RaceDetail>(`/race-strategy/${id}`),
  });

  const mutation = useMutation({
    mutationFn: (payload: RaceFormData) =>
      api.put(`/race-strategy/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push(`/app/race-strategy/${id}`);
    },
    onError: (err: Error) => setError(err.message),
  });

  function handleSubmit(formData: RaceFormData) {
    setError('');
    mutation.mutate(formData);
  }

  if (isLoading) return <div className="p-8 text-steel font-body">Loading race configuration...</div>;
  if (!data) return <div className="p-8 text-safety-red font-body">Race not found</div>;

  return (
    <div className="max-w-4xl">
      <PageHeader title="Edit Race" subtitle={String(data.race.race_name || 'Update race configuration')} />

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 text-safety-red font-body text-sm">
          {error}
        </div>
      )}

      <RaceConfigForm
        mode="edit"
        initialData={{
          race: data.race,
          drivers: data.drivers,
          windows: data.windows,
        }}
        raceStrategyLimit={raceStrategyLimit}
        onSubmit={handleSubmit}
        onCancel={() => router.back()}
        isSubmitting={mutation.isPending}
      />
    </div>
  );
}
