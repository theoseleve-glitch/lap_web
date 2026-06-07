'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import { MasteryStars } from './MasteryStars';

interface TrackMastery {
  track_id: string; track_name: string;
  stars: { bronze: number; silver: number; gold: number };
  corners_starred: number;
}

export function TerritoryShelf() {
  const { data } = useQuery<{ tracks: TrackMastery[] }>({
    queryKey: ['mastery', 'tracks'],
    queryFn: () => apiFetch('/mastery/tracks'),
    staleTime: 60_000,
  });
  const tracks = data?.tracks ?? [];
  if (tracks.length === 0) return null;
  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-5">
      <h2 className="text-sm font-monument text-chalk mb-3">Territories</h2>
      <div className="flex gap-3 flex-wrap">
        {tracks.map((t) => (
          <div key={t.track_id} className="bg-asphalt rounded-lg border border-steel/15 px-4 py-3 min-w-[150px]">
            <p className="font-telemetry text-xs text-chalk truncate mb-2">{t.track_name}</p>
            <div className="flex items-center gap-3">
              {(['gold', 'silver', 'bronze'] as const).map((tier) => (
                <span key={tier} className="flex items-center gap-1 font-telemetry text-[11px] text-steel">
                  <MasteryStars tier={tier} /> {t.stars[tier]}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
