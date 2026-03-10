'use client';

import Link from 'next/link';
import type { DriverSession } from '@/lib/api-types';

interface Props {
  sessions: DriverSession[];
}

function fmtTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

export function DriverSessionsTable({ sessions }: Props) {
  if (sessions.length === 0) {
    return (
      <p className="text-steel font-body text-sm text-center py-6">No sessions found.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-steel/20">
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase">Date</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase">Track</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Laps</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Best Time</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Score</th>
            <th className="pb-2 font-telemetry text-[10px] text-steel/60 uppercase text-right">Conditions</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.session_id} className="border-b border-steel/10 hover:bg-steel/5 transition-colors">
              <td className="py-2.5 font-telemetry text-xs text-chalk">
                <Link href={`/app/sessions/${s.session_id}`} className="hover:text-acid-green transition-colors">
                  {s.session_date ?? '\u2014'}
                </Link>
              </td>
              <td className="py-2.5 font-body text-sm text-chalk">{s.track_name ?? '\u2014'}</td>
              <td className="py-2.5 font-telemetry text-xs text-steel text-right">{s.n_laps ?? '\u2014'}</td>
              <td className="py-2.5 font-telemetry text-xs text-acid-green text-right">{fmtTime(s.best_lap_time_s)}</td>
              <td className={`py-2.5 font-telemetry text-xs text-right ${scoreColor(s.total_score)}`}>
                {s.total_score?.toFixed(1) ?? '\u2014'}
              </td>
              <td className="py-2.5 font-telemetry text-[10px] text-steel/60 text-right uppercase">
                {s.track_state ?? '\u2014'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
