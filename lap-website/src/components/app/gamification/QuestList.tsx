'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import { QuestCard, type Quest } from './QuestCard';

/** Dashboard widget — fetches active quests via /quests, provides focus toggle. */
export function QuestList() {
  const qc = useQueryClient();

  const { data } = useQuery<{ quests: Quest[] }>({
    queryKey: ['quests'],
    queryFn: () => apiFetch('/quests'),
    staleTime: 60_000,
  });

  const focus = useMutation({
    mutationFn: ({ id, focused }: { id: number; focused: boolean }) =>
      apiFetch(`/quests/${id}/focus`, {
        method: 'POST',
        body: JSON.stringify({ focused }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['quests'] }),
  });

  const quests = (data?.quests ?? []).filter((q) => q.status === 'active');
  if (quests.length === 0) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-5">
      <h2 className="text-sm font-monument text-chalk mb-3">Your Quests</h2>
      <div className="flex flex-col gap-2">
        {quests.map((q) => (
          <QuestCard
            key={q.id}
            quest={q}
            onFocus={(id, f) => focus.mutate({ id, focused: f })}
          />
        ))}
      </div>
    </div>
  );
}
