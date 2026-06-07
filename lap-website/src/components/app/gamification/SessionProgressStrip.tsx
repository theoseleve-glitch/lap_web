'use client';

import { MasteryStars } from './MasteryStars';

interface StarEvent { track_id: string; corner_id: number; tier: string; xp: number; score: number }
interface Gam {
  xp_gained?: number; leveled_up?: boolean; new_level?: number;
  current_streak?: number; stars?: StarEvent[];
  new_achievements?: Array<{ key: string; label: string }>;
  pit_passes?: number;
  pit_pass_used?: boolean;
}

/** One-glance "what moved this session" strip for the session report. */
export function SessionProgressStrip({ gam }: { gam?: Gam | null }) {
  if (!gam) return null;
  const stars = gam.stars ?? [];
  const achievements = gam.new_achievements ?? [];
  if (!gam.xp_gained && stars.length === 0 && achievements.length === 0) return null;
  return (
    <div className="bg-concrete rounded-lg border border-steel/15 px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-2">
      {Boolean(gam.xp_gained) && (
        <span className="font-telemetry text-xs text-marshal-yellow">+{gam.xp_gained} XP</span>
      )}
      {gam.leveled_up && (
        <span className="font-telemetry text-xs text-acid-green">LEVEL {gam.new_level} ↑</span>
      )}
      {stars.map((s) => (
        <span key={`${s.corner_id}-${s.tier}`} className="flex items-center gap-1 font-telemetry text-xs text-chalk">
          <MasteryStars tier={s.tier} /> T{s.corner_id}
        </span>
      ))}
      {achievements.map((a) => (
        <span key={a.key} className="font-telemetry text-xs text-steel">🏆 {a.label}</span>
      ))}
      {/* Pit-Pass pips — banked freezes the driver can spend on a missed week */}
      {gam.pit_passes != null && gam.pit_passes > 0 && (
        <span className="flex items-center gap-0.5 font-telemetry text-[10px] text-marshal-yellow" title="Banked Pit Passes">
          {Array.from({ length: gam.pit_passes }).map((_, i) => (
            <span key={i} aria-hidden="true">◆</span>
          ))}
          <span className="ml-1">pit{gam.pit_passes !== 1 ? ' passes' : ' pass'}</span>
        </span>
      )}
      {gam.pit_pass_used && (
        <span className="font-telemetry text-[10px] text-marshal-yellow/80">
          Pit Pass used — streak saved.
        </span>
      )}
    </div>
  );
}
