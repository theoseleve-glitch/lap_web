'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';

interface Recap {
  iso_week: string;
  xp_gained?: number;
  stars_earned?: number;
  quests_completed: number;
  current_streak: number;
  next_focus: string | null;
}

/** "Your week in the kart" — fetches /recap/latest, self-hides when recap is null. */
export function RecapCard() {
  const { data } = useQuery<{ recap: Recap | null }>({
    queryKey: ['recap', 'latest'],
    queryFn: () => apiFetch('/recap/latest'),
    staleTime: 300_000,
  });

  const r = data?.recap;
  if (!r) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-5">
      <h2 className="text-sm font-monument text-chalk mb-2">Your week in the kart</h2>
      <div className="flex flex-wrap gap-x-6 gap-y-1 font-telemetry text-xs text-steel">
        {r.xp_gained != null && r.xp_gained > 0 && (
          <span className="text-marshal-yellow">+{r.xp_gained} XP</span>
        )}
        {r.stars_earned != null && r.stars_earned > 0 && (
          <span className="text-chalk">{r.stars_earned} star{r.stars_earned !== 1 ? 's' : ''}</span>
        )}
        <span className="text-chalk">{r.quests_completed} quest{r.quests_completed !== 1 ? 's' : ''} done</span>
        <span>streak {r.current_streak}</span>
        {r.next_focus && (
          <span>
            next:{' '}
            <span className="text-marshal-yellow">{r.next_focus}</span>
          </span>
        )}
      </div>
    </div>
  );
}
