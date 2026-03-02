'use client';

interface Stint {
  stint_id: number;
  stint_order: number;
  driver_id: number;
  driver_name: string;
  planned_duration_s: number | null;
  actual_duration_s: number | null;
  status: string;
}

interface StintTimelineProps {
  stints: Stint[];
  totalDuration: number;
  driverColors: Record<number, string>;
  /** Set to the active stint_id to highlight it with a green ring (live page). */
  activeStintId?: number;
  /** When true, prefer actual_duration_s over planned (summary page). */
  preferActual?: boolean;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '\u2014';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

export function StintTimeline({
  stints,
  totalDuration,
  driverColors,
  activeStintId,
  preferActual = false,
}: StintTimelineProps) {
  if (!stints.length || !totalDuration) return null;
  return (
    <div className="flex h-10 w-full overflow-hidden border border-steel/20 rounded">
      {stints.map((s) => {
        const dur = preferActual
          ? (s.actual_duration_s || s.planned_duration_s || 0)
          : (s.planned_duration_s || s.actual_duration_s || 0);
        const pct = (dur / totalDuration) * 100;
        const bg = driverColors[s.driver_id] || '#888';
        const isActive = s.stint_id === activeStintId;
        return (
          <div
            key={s.stint_id}
            className={`flex items-center justify-center text-[10px] font-telemetry text-asphalt truncate border-r border-asphalt/30 last:border-r-0 ${
              isActive ? 'ring-2 ring-acid-green ring-inset animate-pulse' : ''
            }`}
            style={{ width: `${pct}%`, backgroundColor: bg }}
            title={`${s.driver_name} \u2014 ${formatTime(dur)}`}
          >
            {pct > 8 ? s.driver_name : ''}
          </div>
        );
      })}
    </div>
  );
}
