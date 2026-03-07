'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageIntro } from '@/components/ui/PageIntro';
import { useEntitlementsStore } from '@/lib/entitlements-store';
import { RaceConfigForm, type RaceFormData } from '@/components/app/race-strategy/RaceConfigForm';

export default function NewRacePage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const raceStrategyLimit = useEntitlementsStore((s) => s.entitlements?.raceStrategyLimit) ?? undefined;

  const mutation = useMutation({
    mutationFn: (payload: RaceFormData) =>
      api.post<{ race_id: number }>('/race-strategy/', payload),
    onSuccess: (data) => {
      router.push(`/app/race-strategy/${data.race_id}`);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  function handleSubmit(data: RaceFormData) {
    setError('');
    mutation.mutate(data);
  }

  return (
    <div className="max-w-4xl">
      <PageIntro title="New Race" subtitle="Configure your endurance race strategy" />

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 text-safety-red font-body text-sm">
          {error}
        </div>
      )}

      <RaceConfigForm
        mode="create"
        raceStrategyLimit={raceStrategyLimit}
        onSubmit={handleSubmit}
        onCancel={() => router.back()}
        isSubmitting={mutation.isPending}
      />
    </div>
  );
}
